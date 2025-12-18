#!/usr/bin/env python3
"""
Ryu DDoS Detection Controller with Rule-Based Mitigation
=========================================================

This application implements packet rate-based DDoS detection and mitigation
using configurable JSON rules with support for single and multi-feature thresholds.

FEATURES:
- Monitor Packets Per Second (PPS) and Bytes Per Second (BPS) per source IP
- Multi-feature threat detection with AND/OR logic
- Configurable detection rules via JSON
- Temporary and permanent IP blocking
- Real-time threshold updates via REST API
- Whitelist support for trusted IPs
- Automatic temporary block expiration
- Comprehensive activity logging and statistics

DETECTION RULES (JSON Format):
- Single-feature: Block if PPS OR BPS exceeds threshold
- Multi-feature: Block if (PPS AND BPS) or (PPS OR BPS) based on logic setting
- Blocking types: Temporary (auto-expire) or Permanent (manual unblock)
- Whitelist: IPs that are never blocked

REST API ENDPOINTS:
- GET  /hello              - Health check
- GET  /config             - View current configuration
- POST /config             - Update configuration (real-time)
- GET  /blocked            - List currently blocked IPs
- POST /unblock/<ip>       - Manually unblock an IP
- GET  /stats              - View traffic statistics per IP
- GET  /activity           - View recent detection events
- GET  /whitelist          - View whitelist IPs
- POST /whitelist          - Add IP to whitelist
- POST /reset              - Clear all statistics and blocks
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, ipv4
from ryu.app.wsgi import WSGIApplication, route, ControllerBase

import json
import time
import threading
import os
from datetime import datetime
from collections import defaultdict, deque
from webob import Response


class DDoSDetectionController(app_manager.RyuApp):
    """Ryu application for DDoS detection and mitigation"""

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(DDoSDetectionController, self).__init__(*args, **kwargs)

        # Switch management
        self.switches = {}
        self.mac_to_port = {}

        # Traffic statistics tracking per source IP
        self.traffic_stats = defaultdict(lambda: {
            'packet_count': 0,
            'byte_count': 0,
            'first_seen': time.time(),
            'last_seen': time.time(),
            'pps': 0.0,
            'bps': 0.0,
            'packet_history': deque(maxlen=10000)  # Store recent packets for rate calculation
        })

        # Blocked IPs dictionary
        self.blocked_ips = {}

        # Activity log (circular buffer)
        self.activity_log = []
        self.max_log_entries = 200

        # Statistics
        self.start_time = time.time()
        self.total_packet_count = 0
        self.total_byte_count = 0

        # Load configuration
        self.config = self._load_config()
        self.detection_rules = self.config.get('detection_rules', [])
        self.whitelist = set(self.config.get('whitelist', []))

        # REST API registration
        if 'wsgi' in kwargs:
            wsgi = kwargs['wsgi']
            wsgi.register(DDoSDetectionAPI, self)
        else:
            self.logger.warning("WSGI not provided - REST API will not be available")

        # Start background threads
        self.stats_thread = threading.Thread(target=self._stats_updater_thread)
        self.stats_thread.daemon = True
        self.stats_thread.start()

        self.detection_thread = threading.Thread(target=self._threat_detector_thread)
        self.detection_thread.daemon = True
        self.detection_thread.start()

        self.log_activity('info', 'DDoS Detection Controller started')

    def _load_config(self):
        """Load configuration from JSON file"""
        config_path = '/opt/ukmsdn/examples/ddos_config.json'

        # Try to load from container path
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    self.logger.info(f"Loaded configuration from {config_path}")
                    return config
            except Exception as e:
                self.logger.warning(f"Failed to load config from {config_path}: {e}")

        # Fallback to default configuration
        default_config = {
            "detection_rules": [
                {
                    "name": "volumetric_flood",
                    "enabled": True,
                    "logic": "OR",
                    "thresholds": {"pps": 1000, "bps": 10485760},
                    "action": {"type": "temporary", "duration": 300}
                },
                {
                    "name": "sustained_attack",
                    "enabled": True,
                    "logic": "AND",
                    "thresholds": {"pps": 500, "bps": 5242880},
                    "action": {"type": "permanent"}
                }
            ],
            "whitelist": [],
            "monitoring_window": 10,
            "check_interval": 5
        }

        self.logger.info("Using default DDoS detection configuration")
        return default_config

    def log_activity(self, level, message):
        """Log activity message"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        entry = {'timestamp': timestamp, 'level': level, 'message': message}
        self.activity_log.append(entry)

        # Keep circular buffer size
        if len(self.activity_log) > self.max_log_entries:
            self.activity_log.pop(0)

        # Also log via Ryu logger
        if level.upper() == 'INFO':
            self.logger.info(message)
        elif level.upper() == 'WARNING':
            self.logger.warning(message)
        elif level.upper() == 'ERROR':
            self.logger.error(message)
        elif level.upper() == 'DEBUG':
            self.logger.debug(message)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Handle switch connection"""
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id

        # Register switch
        self.switches[dpid] = {
            'datapath': datapath,
            'connected_time': time.time()
        }

        # Install table-miss flow entry (send to controller)
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

        self.log_activity('info', f'Switch {hex(dpid)} connected')

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """Handle incoming packets"""
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']
        dpid = datapath.id

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        # Ignore LLDP packets
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        # Update overall statistics
        self.total_packet_count += 1
        self.total_byte_count += len(msg.data)

        # Track MAC to port for L2 switching
        self.mac_to_port.setdefault(dpid, {})
        src_mac = eth.src
        self.mac_to_port[dpid][src_mac] = in_port

        # Extract source IP if this is an IP packet
        src_ip = None
        if eth.ethertype == ether_types.ETH_TYPE_IP:
            ip_pkt = pkt.get_protocol(ipv4.ipv4)
            if ip_pkt:
                src_ip = ip_pkt.src

        # Update traffic statistics
        if src_ip:
            stats = self.traffic_stats[src_ip]
            stats['packet_count'] += 1
            stats['byte_count'] += len(msg.data)
            stats['last_seen'] = time.time()
            stats['packet_history'].append({
                'time': time.time(),
                'bytes': len(msg.data)
            })

        # Standard L2 switching
        dst_mac = eth.dst
        out_port = self.mac_to_port[dpid].get(dst_mac, ofproto.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]

        # Install flow rule if not flooding
        if out_port != ofproto.OFPP_FLOOD and eth.ethertype != ether_types.ETH_TYPE_IP:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst_mac, eth_src=src_mac)
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, 1, match, actions, msg.buffer_id)
            else:
                self.add_flow(datapath, 1, match, actions)

        # Send packet out
        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data
        )
        datapath.send_msg(out)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None,
                 idle_timeout=30, hard_timeout=0):
        """Install a flow rule"""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

        mod_kwargs = {
            'datapath': datapath,
            'priority': priority,
            'match': match,
            'instructions': inst,
            'idle_timeout': idle_timeout,
            'hard_timeout': hard_timeout
        }

        if buffer_id:
            mod_kwargs['buffer_id'] = buffer_id

        mod = parser.OFPFlowMod(**mod_kwargs)
        datapath.send_msg(mod)

    def _calculate_rates(self, src_ip):
        """Calculate PPS and BPS for a source IP"""
        stats = self.traffic_stats[src_ip]
        window = self.config.get('monitoring_window', 10)
        now = time.time()

        # Get packets within monitoring window
        cutoff_time = now - window
        packet_history = stats['packet_history']

        # Count recent packets and bytes
        recent_packets = [p for p in packet_history if p['time'] > cutoff_time]

        if recent_packets:
            pps = len(recent_packets) / window if window > 0 else 0
            bps = sum(p['bytes'] for p in recent_packets) / window if window > 0 else 0
        else:
            pps = bps = 0.0

        return pps, bps

    def _evaluate_rule(self, rule, stats):
        """Evaluate if a detection rule is triggered"""
        if not rule.get('enabled', True):
            return False

        logic = rule.get('logic', 'OR')
        thresholds = rule.get('thresholds', {})

        conditions_met = []

        # Check PPS threshold
        if 'pps' in thresholds:
            conditions_met.append(stats['pps'] > thresholds['pps'])

        # Check BPS threshold
        if 'bps' in thresholds:
            conditions_met.append(stats['bps'] > thresholds['bps'])

        # Evaluate logic
        if not conditions_met:
            return False

        if logic == 'AND':
            return all(conditions_met)
        else:  # OR
            return any(conditions_met)

    def _block_ip(self, src_ip, rule):
        """Block traffic from a source IP"""
        if src_ip in self.whitelist:
            self.logger.debug(f"IP {src_ip} is whitelisted, not blocking")
            return

        if src_ip in self.blocked_ips:
            # Already blocked
            return

        # Install drop flow on all switches
        for dpid, switch_info in self.switches.items():
            datapath = switch_info['datapath']
            parser = datapath.ofproto_parser

            # Match on source IP
            match = parser.OFPMatch(
                eth_type=ether_types.ETH_TYPE_IP,
                ipv4_src=src_ip
            )

            # Empty actions = drop
            actions = []

            # Determine timeout
            if rule['action']['type'] == 'permanent':
                hard_timeout = 0
            else:
                hard_timeout = rule['action'].get('duration', 300)

            # Install drop flow
            self.add_flow(datapath, priority=100, match=match, actions=actions,
                         idle_timeout=0, hard_timeout=hard_timeout)

        # Record blocking
        self.blocked_ips[src_ip] = {
            'block_time': time.time(),
            'duration': hard_timeout,
            'rule': rule['name'],
            'pps': self.traffic_stats[src_ip]['pps'],
            'bps': self.traffic_stats[src_ip]['bps']
        }

        msg = f"BLOCKED: {src_ip} - Rule: {rule['name']} | PPS: {self.traffic_stats[src_ip]['pps']:.1f} | BPS: {self.traffic_stats[src_ip]['bps']:.1f}"
        self.log_activity('warning', msg)

    def _unblock_ip(self, src_ip):
        """Unblock traffic from a source IP"""
        if src_ip not in self.blocked_ips:
            return False

        # Remove drop flow from all switches
        for dpid, switch_info in self.switches.items():
            datapath = switch_info['datapath']
            parser = datapath.ofproto_parser
            ofproto = datapath.ofproto

            # Create match for source IP
            match = parser.OFPMatch(
                eth_type=ether_types.ETH_TYPE_IP,
                ipv4_src=src_ip
            )

            # Create flow_mod to delete flows
            mod = parser.OFPFlowMod(
                datapath=datapath,
                match=match,
                command=ofproto.OFPFC_DELETE,
                priority=100
            )
            datapath.send_msg(mod)

        del self.blocked_ips[src_ip]
        self.log_activity('info', f"UNBLOCKED: {src_ip}")
        return True

    def _stats_updater_thread(self):
        """Background thread: Update traffic statistics"""
        while True:
            try:
                time.sleep(1)
                now = time.time()

                # Update rates for all tracked IPs
                inactive_ips = []
                for src_ip in list(self.traffic_stats.keys()):
                    stats = self.traffic_stats[src_ip]

                    # Calculate current rates
                    pps, bps = self._calculate_rates(src_ip)
                    stats['pps'] = pps
                    stats['bps'] = bps

                    # Remove inactive IPs (no traffic for 60 seconds)
                    if now - stats['last_seen'] > 60:
                        inactive_ips.append(src_ip)

                # Clean up inactive IPs
                for ip in inactive_ips:
                    del self.traffic_stats[ip]

            except Exception as e:
                self.logger.error(f"Error in stats updater: {e}")

    def _threat_detector_thread(self):
        """Background thread: Detect threats and block IPs"""
        while True:
            try:
                check_interval = self.config.get('check_interval', 5)
                time.sleep(check_interval)

                now = time.time()

                # Check for new threats
                for src_ip in list(self.traffic_stats.keys()):
                    # Skip if already blocked
                    if src_ip in self.blocked_ips:
                        continue

                    # Skip if whitelisted
                    if src_ip in self.whitelist:
                        continue

                    stats = self.traffic_stats[src_ip]

                    # Evaluate all detection rules
                    for rule in self.detection_rules:
                        if self._evaluate_rule(rule, stats):
                            self._block_ip(src_ip, rule)
                            break  # Block on first matched rule

                # Check for expired temporary blocks
                expired_ips = []
                for src_ip, block_info in self.blocked_ips.items():
                    if block_info['duration'] > 0:  # Temporary block
                        block_age = now - block_info['block_time']
                        if block_age > block_info['duration']:
                            expired_ips.append(src_ip)

                # Unblock expired IPs
                for ip in expired_ips:
                    self._unblock_ip(ip)

            except Exception as e:
                self.logger.error(f"Error in threat detector: {e}")

    def update_config(self, new_config):
        """Update configuration from JSON"""
        try:
            # Validate structure
            if 'detection_rules' not in new_config:
                raise ValueError("Missing 'detection_rules' in configuration")

            # Apply new configuration
            self.config = new_config
            self.detection_rules = new_config.get('detection_rules', [])
            self.whitelist = set(new_config.get('whitelist', []))

            self.log_activity('info', 'Configuration updated via REST API')
            return True, "Configuration updated successfully"

        except Exception as e:
            self.log_activity('error', f"Configuration update failed: {e}")
            return False, str(e)

    def get_stats_summary(self):
        """Get statistics summary for all tracked IPs"""
        summary = []
        for src_ip, stats in self.traffic_stats.items():
            summary.append({
                'source_ip': src_ip,
                'packet_count': stats['packet_count'],
                'byte_count': stats['byte_count'],
                'pps': round(stats['pps'], 2),
                'bps': round(stats['bps'], 2),
                'first_seen': datetime.fromtimestamp(stats['first_seen']).isoformat(),
                'last_seen': datetime.fromtimestamp(stats['last_seen']).isoformat(),
                'blocked': src_ip in self.blocked_ips
            })
        return summary

    def get_blocked_summary(self):
        """Get summary of blocked IPs"""
        summary = []
        for src_ip, block_info in self.blocked_ips.items():
            block_age = time.time() - block_info['block_time']
            summary.append({
                'source_ip': src_ip,
                'rule': block_info['rule'],
                'block_type': 'permanent' if block_info['duration'] == 0 else 'temporary',
                'duration': block_info['duration'],
                'blocked_at': datetime.fromtimestamp(block_info['block_time']).isoformat(),
                'block_age_seconds': round(block_age, 2),
                'triggered_pps': round(block_info['pps'], 2),
                'triggered_bps': round(block_info['bps'], 2)
            })
        return summary


class DDoSDetectionAPI(ControllerBase):
    """REST API for DDoS Detection Controller"""

    def __init__(self, req, link, data, **config):
        super(DDoSDetectionAPI, self).__init__(req, link, data, **config)
        self.controller_app = data

    @route('hello', '/hello', methods=['GET'])
    def hello(self, req, **kwargs):
        """Health check endpoint"""
        try:
            response = {"message": "Hello from Ryu DDoS Detection Controller!"}
            body = json.dumps(response).encode('utf-8')
            return Response(content_type='application/json; charset=utf-8', body=body)
        except Exception as e:
            return Response(status=500, body=json.dumps({"error": str(e)}).encode('utf-8'))

    @route('config', '/config', methods=['GET'])
    def get_config(self, req, **kwargs):
        """Get current configuration"""
        try:
            body = json.dumps(self.controller_app.config, indent=2).encode('utf-8')
            return Response(content_type='application/json; charset=utf-8', body=body)
        except Exception as e:
            return Response(status=500, body=json.dumps({"error": str(e)}).encode('utf-8'))

    @route('config', '/config', methods=['POST'])
    def update_config(self, req, **kwargs):
        """Update configuration in real-time"""
        try:
            new_config = json.loads(req.body.decode('utf-8'))
            success, message = self.controller_app.update_config(new_config)

            if success:
                response = {"status": "success", "message": message}
                body = json.dumps(response).encode('utf-8')
                return Response(content_type='application/json; charset=utf-8', body=body)
            else:
                response = {"status": "error", "message": message}
                body = json.dumps(response).encode('utf-8')
                return Response(status=400, content_type='application/json; charset=utf-8', body=body)
        except Exception as e:
            response = {"status": "error", "message": str(e)}
            body = json.dumps(response).encode('utf-8')
            return Response(status=500, content_type='application/json; charset=utf-8', body=body)

    @route('blocked', '/blocked', methods=['GET'])
    def get_blocked(self, req, **kwargs):
        """Get list of blocked IPs"""
        try:
            blocked = self.controller_app.get_blocked_summary()
            body = json.dumps(blocked, indent=2).encode('utf-8')
            return Response(content_type='application/json; charset=utf-8', body=body)
        except Exception as e:
            return Response(status=500, body=json.dumps({"error": str(e)}).encode('utf-8'))

    @route('unblock', '/unblock/{src_ip}', methods=['POST'])
    def unblock_ip(self, req, src_ip, **kwargs):
        """Manually unblock an IP"""
        try:
            success = self.controller_app._unblock_ip(src_ip)

            if success:
                response = {"status": "success", "message": f"IP {src_ip} unblocked"}
                body = json.dumps(response).encode('utf-8')
                return Response(content_type='application/json; charset=utf-8', body=body)
            else:
                response = {"status": "error", "message": f"IP {src_ip} is not blocked"}
                body = json.dumps(response).encode('utf-8')
                return Response(status=400, content_type='application/json; charset=utf-8', body=body)
        except Exception as e:
            response = {"status": "error", "message": str(e)}
            body = json.dumps(response).encode('utf-8')
            return Response(status=500, content_type='application/json; charset=utf-8', body=body)

    @route('stats', '/stats', methods=['GET'])
    def get_stats(self, req, **kwargs):
        """Get traffic statistics"""
        try:
            stats = self.controller_app.get_stats_summary()
            body = json.dumps(stats, indent=2).encode('utf-8')
            return Response(content_type='application/json; charset=utf-8', body=body)
        except Exception as e:
            return Response(status=500, body=json.dumps({"error": str(e)}).encode('utf-8'))

    @route('activity', '/activity', methods=['GET'])
    def get_activity(self, req, **kwargs):
        """Get recent activity log"""
        try:
            body = json.dumps(self.controller_app.activity_log, indent=2).encode('utf-8')
            return Response(content_type='application/json; charset=utf-8', body=body)
        except Exception as e:
            return Response(status=500, body=json.dumps({"error": str(e)}).encode('utf-8'))

    @route('whitelist', '/whitelist', methods=['GET'])
    def get_whitelist(self, req, **kwargs):
        """Get whitelist IPs"""
        try:
            whitelist = list(self.controller_app.whitelist)
            response = {"whitelist": whitelist}
            body = json.dumps(response).encode('utf-8')
            return Response(content_type='application/json; charset=utf-8', body=body)
        except Exception as e:
            return Response(status=500, body=json.dumps({"error": str(e)}).encode('utf-8'))

    @route('whitelist', '/whitelist', methods=['POST'])
    def add_whitelist(self, req, **kwargs):
        """Add IP to whitelist"""
        try:
            data = json.loads(req.body.decode('utf-8'))
            ip = data.get('ip')

            if not ip:
                response = {"status": "error", "message": "Missing 'ip' parameter"}
                body = json.dumps(response).encode('utf-8')
                return Response(status=400, content_type='application/json; charset=utf-8', body=body)

            self.controller_app.whitelist.add(ip)
            self.controller_app.log_activity('info', f"IP {ip} added to whitelist")

            response = {"status": "success", "message": f"IP {ip} added to whitelist"}
            body = json.dumps(response).encode('utf-8')
            return Response(content_type='application/json; charset=utf-8', body=body)
        except Exception as e:
            response = {"status": "error", "message": str(e)}
            body = json.dumps(response).encode('utf-8')
            return Response(status=500, content_type='application/json; charset=utf-8', body=body)

    @route('reset', '/reset', methods=['POST'])
    def reset_all(self, req, **kwargs):
        """Reset all statistics and blocks"""
        try:
            # Unblock all IPs
            for src_ip in list(self.controller_app.blocked_ips.keys()):
                self.controller_app._unblock_ip(src_ip)

            # Clear statistics
            self.controller_app.traffic_stats.clear()
            self.controller_app.total_packet_count = 0
            self.controller_app.total_byte_count = 0

            self.controller_app.log_activity('info', 'All statistics and blocks reset')

            response = {"status": "success", "message": "All statistics and blocks reset"}
            body = json.dumps(response).encode('utf-8')
            return Response(content_type='application/json; charset=utf-8', body=body)
        except Exception as e:
            response = {"status": "error", "message": str(e)}
            body = json.dumps(response).encode('utf-8')
            return Response(status=500, content_type='application/json; charset=utf-8', body=body)
