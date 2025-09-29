#!/usr/bin/env python3
"""
Ryu Layer 3 Routing Controller for Multi-Subnet Topology
Supports 4-subnet routing with ARP proxy and flow monitoring
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, arp, ipv4, tcp, udp, icmp
from ryu.topology import event as topo_event
from ryu.topology.api import get_switch, get_link, get_host
from ryu.app.wsgi import WSGIApplication, route, ControllerBase

import json
import time
import threading
from datetime import datetime
from collections import defaultdict
from webob import Response
import ipaddress

# Import standardized logging (with fallback for Ryu environment)
try:
    from ..utils.logger import get_controller_logger
except ImportError:
    try:
        from utils.logger import get_controller_logger
    except ImportError:
        def get_controller_logger(log_dir=None):
            import logging
            return logging.getLogger('ryu.app.L3RouterController')

class L3RouterController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(L3RouterController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.ip_to_mac = {}
        self.switches = {}
        self.links = {}
        self.flow_stats = defaultdict(dict)
        self.port_stats = defaultdict(dict)
        self.activity_log = []
        self.start_time = time.time()
        self.packet_count = 0
        self.byte_count = 0

        # Cache for ARP probes to avoid excessive broadcasts
        self._arp_probe_cache = {}
        self._discovered_hosts = set()

        # Layer 3 routing configuration (matching 4-internetwork.py topology)
        self.subnet_gateways = {
            '10.0.0.0/24': {'gateway_ip': '10.0.0.254', 'gateway_mac': '00:00:00:00:10:01'},
            '172.16.0.0/24': {'gateway_ip': '172.16.0.254', 'gateway_mac': '00:00:00:00:20:01'},
            '192.168.0.0/24': {'gateway_ip': '192.168.0.254', 'gateway_mac': '00:00:00:00:30:01'}
        }

        # Routing table - subnet to subnet routing
        self.routing_table = {}
        for subnet in self.subnet_gateways:
            self.routing_table[subnet] = {}
            for other_subnet in self.subnet_gateways:
                if subnet != other_subnet:
                    self.routing_table[subnet][other_subnet] = {'next_hop': self.subnet_gateways[other_subnet]['gateway_ip']}

        if 'wsgi' in kwargs:
            wsgi = kwargs['wsgi']
            wsgi.register(L3RouterAPI, self)
        else:
            self.logger.warning("WSGI context not provided. REST API will not be available.")

        # Initialize standardized logging
        try:
            self.std_logger = get_controller_logger()
        except:
            self.std_logger = self.logger
            
        self.stats_thread = threading.Thread(target=self._collect_stats_periodically)
        self.stats_thread.daemon = True
        self.stats_thread.start()
        self.log_activity('info', 'L3 Router Controller started')
        self.std_logger.info('L3 Router Controller started with 4-subnet support')

    def log_activity(self, level, message):
        timestamp = datetime.now().strftime('%H:%M:%S')
        entry = {'timestamp': timestamp, 'level': level, 'message': message}
        self.activity_log.append(entry)
        if len(self.activity_log) > 100:
            self.activity_log.pop(0)
        self.logger.info(f"[{level.upper()}] {message}")

    def get_subnet_for_ip(self, ip_address):
        """Determine which subnet an IP address belongs to"""
        try:
            ip_obj = ipaddress.ip_address(ip_address)
            for subnet_str in self.subnet_gateways:
                subnet = ipaddress.ip_network(subnet_str)
                if ip_obj in subnet:
                    return subnet_str
        except:
            pass
        return None

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id

        self.switches[dpid] = {
            'datapath': datapath,
            'ports': {},
            'flows': 0,
            'connected_time': time.time()
        }

        # Install table-miss flow entry
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        self.log_activity('info', f'Switch {hex(dpid)} connected with L3 routing support')

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']
        dpid = datapath.id

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src

        self.packet_count += 1
        self.byte_count += len(msg.data)

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port
        
        # Debug packet reception
        if eth.ethertype == ether_types.ETH_TYPE_ARP:
            self.log_activity('debug', f'PACKET_IN: ARP packet {src} -> {dst} on port {in_port}')
        elif eth.ethertype == ether_types.ETH_TYPE_IP:
            ip_pkt = pkt.get_protocol(ipv4.ipv4)
            if ip_pkt:
                self.log_activity('debug', f'PACKET_IN: IP packet {ip_pkt.src} -> {ip_pkt.dst} (MAC: {src} -> {dst}) on port {in_port}')

        # Handle ARP packets
        if eth.ethertype == ether_types.ETH_TYPE_ARP:
            self.handle_arp(datapath, in_port, eth, pkt)
            return

        # Handle IP packets
        elif eth.ethertype == ether_types.ETH_TYPE_IP:
            ip_pkt = pkt.get_protocol(ipv4.ipv4)
            if ip_pkt:
                self.handle_ip(datapath, in_port, eth, ip_pkt, pkt)
                return

        # Default L2 switching for other packets
        self.log_activity('debug', f'PACKET_IN: L2 switching for {src} -> {dst} (ethertype: {hex(eth.ethertype)})')
        out_port = self.mac_to_port[dpid].get(dst, ofproto.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, 1, match, actions, msg.buffer_id)
            else:
                self.add_flow(datapath, 1, match, actions)

        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id, 
                                 in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

    def handle_arp(self, datapath, in_port, eth_pkt, pkt):
        """Handle ARP packets with gateway proxy functionality"""
        arp_pkt = pkt.get_protocol(arp.arp)
        if not arp_pkt:
            return

        # Learn IP to MAC mapping and mark as discovered
        self.ip_to_mac[arp_pkt.src_ip] = arp_pkt.src_mac
        self.log_activity('debug', f'ARP: Learned {arp_pkt.src_ip} -> {arp_pkt.src_mac}')
        
        if arp_pkt.src_ip not in self._discovered_hosts:
            self._discovered_hosts.add(arp_pkt.src_ip)
            self.log_activity('info', f'HOST DISCOVERED via ARP: {arp_pkt.src_ip} at {arp_pkt.src_mac}')
            src_subnet = self.get_subnet_for_ip(arp_pkt.src_ip)
            if src_subnet:
                self._trigger_host_discovery(datapath, src_subnet)

        if arp_pkt.opcode == arp.ARP_REQUEST:
            # Check if this is a request for one of our gateway IPs
            target_ip = arp_pkt.dst_ip
            gateway_mac = None
            
            self.log_activity('debug', f'ARP REQUEST: {arp_pkt.src_ip} ({arp_pkt.src_mac}) asking for {target_ip}')
            
            for subnet_info in self.subnet_gateways.values():
                if target_ip == subnet_info['gateway_ip']:
                    gateway_mac = subnet_info['gateway_mac']
                    break

            if gateway_mac:
                # Send ARP reply as gateway
                self.send_arp_reply(datapath, in_port, gateway_mac, target_ip,
                                  arp_pkt.src_mac, arp_pkt.src_ip)
                self.log_activity('debug', f'ARP REPLY sent: {target_ip} is at {gateway_mac} (gateway proxy)')
            else:
                # Forward ARP request normally for non-gateway IPs
                self.log_activity('debug', f'ARP REQUEST forwarded: {target_ip} is not a gateway IP')
                self.forward_packet(datapath, in_port, pkt)
        elif arp_pkt.opcode == arp.ARP_REPLY:
            self.log_activity('debug', f'ARP REPLY received: {arp_pkt.src_ip} is at {arp_pkt.src_mac}')
            # Forward ARP replies normally
            self.forward_packet(datapath, in_port, pkt)

    def handle_ip(self, datapath, in_port, eth_pkt, ip_pkt, pkt):
        """Handle IP packets with inter-subnet routing"""
        src_ip = ip_pkt.src
        dst_ip = ip_pkt.dst

        # Learn IP to MAC mapping and discover new hosts
        self.ip_to_mac[src_ip] = eth_pkt.src
        self.log_activity('debug', f'IP: Learned {src_ip} -> {eth_pkt.src}')
        
        # Mark host as discovered and potentially trigger discovery of other hosts
        if src_ip not in self._discovered_hosts:
            self._discovered_hosts.add(src_ip)
            self.log_activity('info', f'HOST DISCOVERED: {src_ip} at {eth_pkt.src}')
            # Trigger discovery of other hosts in different subnets
            self._trigger_host_discovery(datapath, src_subnet)

        src_subnet = self.get_subnet_for_ip(src_ip)
        dst_subnet = self.get_subnet_for_ip(dst_ip)

        self.log_activity('debug', f'IP PACKET: {src_ip} ({src_subnet}) -> {dst_ip} ({dst_subnet}) proto={ip_pkt.proto}')

        if not src_subnet or not dst_subnet:
            # Unknown subnet, forward normally
            self.log_activity('warning', f'Unknown subnet: src={src_subnet}, dst={dst_subnet} - forwarding normally')
            self.forward_packet(datapath, in_port, pkt)
            return

        # Check if this is a ping to the gateway
        is_gateway_ping = False
        for subnet_info in self.subnet_gateways.values():
            if dst_ip == subnet_info['gateway_ip']:
                is_gateway_ping = True
                break
        
        if is_gateway_ping:
            # Handle ping to gateway - respond with ICMP echo reply
            self.log_activity('debug', f'Gateway PING: {src_ip} -> {dst_ip} (responding as gateway)')
            self._handle_gateway_ping(datapath, in_port, eth_pkt, ip_pkt, pkt)
        elif src_subnet == dst_subnet:
            # Same subnet - L2 switching
            self.log_activity('debug', f'Same subnet {src_subnet} - L2 switching')
            self.forward_packet(datapath, in_port, pkt)
        else:
            # Inter-subnet routing required
            self.log_activity('debug', f'Inter-subnet routing: {src_subnet} -> {dst_subnet}')
            self.route_packet(datapath, in_port, eth_pkt, ip_pkt, pkt, src_subnet, dst_subnet)

    def route_packet(self, datapath, in_port, eth_pkt, ip_pkt, pkt, src_subnet, dst_subnet):
        """Route packet between subnets"""
        dst_ip = ip_pkt.dst
        
        self.log_activity('debug', f'ROUTING: Attempting to route {dst_ip} from {src_subnet} to {dst_subnet}')
        self.log_activity('debug', f'ROUTING: Known IP-MAC mappings: {dict(list(self.ip_to_mac.items()))}')
        
        # Check if we know the destination MAC
        if dst_ip in self.ip_to_mac:
            dst_mac = self.ip_to_mac[dst_ip]
            # Find output port for destination MAC
            dpid = datapath.id
            out_port = self.mac_to_port.get(dpid, {}).get(dst_mac)
            
            self.log_activity('debug', f'ROUTING: {dst_ip} -> MAC {dst_mac}, out_port={out_port}')
            
            if out_port:
                # Install flow rule for this route
                parser = datapath.ofproto_parser
                match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP,
                                      ipv4_dst=dst_ip)
                gateway_mac = self.subnet_gateways[dst_subnet]['gateway_mac']
                actions = [parser.OFPActionSetField(eth_dst=dst_mac),
                          parser.OFPActionSetField(eth_src=gateway_mac),
                          parser.OFPActionOutput(out_port)]
                self.add_flow(datapath, 10, match, actions)
                
                # Forward current packet
                data = pkt.data if hasattr(pkt, 'data') else None
                out = parser.OFPPacketOut(datapath=datapath, buffer_id=datapath.ofproto.OFP_NO_BUFFER,
                                        in_port=in_port, actions=actions, data=data)
                datapath.send_msg(out)
                self.log_activity('debug', f'ROUTING: Successfully routed {dst_ip} via {gateway_mac} to port {out_port}')
                return
            else:
                self.log_activity('warning', f'ROUTING: No output port found for MAC {dst_mac}')

        # Destination MAC unknown: try broadcasting to find the host
        self.log_activity('debug', f'ROUTING: {dst_ip} MAC unknown, trying broadcast discovery')
        
        # For now, let's try a simpler approach - broadcast the packet to all ports
        # This is less efficient but should work for initial connectivity
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        
        # Create a broadcast action to find the destination
        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        
        # Send the packet via broadcast
        data = pkt.data if hasattr(pkt, 'data') else None
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER,
                                in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)
        self.log_activity('debug', f'ROUTING: Broadcasting packet to {dst_ip} for discovery')
        
        # Also send ARP probe for future packets
        try:
            now = time.time()
            last_probe = self._arp_probe_cache.get(dst_ip, 0)
            if now - last_probe > 1.0:
                self.send_arp_request(datapath, dst_subnet, dst_ip)
                self._arp_probe_cache[dst_ip] = now
                self.log_activity('debug', f'ROUTING: Sent ARP probe for {dst_ip} on {dst_subnet}')
        except Exception as e:
            self.log_activity('warning', f'ROUTING: Failed to send ARP probe for {dst_ip}: {e}')
        
        return

    def forward_packet(self, datapath, in_port, pkt):
        """Forward packet using L2 switching"""
        eth_pkt = pkt.get_protocols(ethernet.ethernet)[0]
        dst = eth_pkt.dst
        dpid = datapath.id
        
        out_port = self.mac_to_port.get(dpid, {}).get(dst, datapath.ofproto.OFPP_FLOOD)
        actions = [datapath.ofproto_parser.OFPActionOutput(out_port)]
        
        data = pkt.data if hasattr(pkt, 'data') else None
        out = datapath.ofproto_parser.OFPPacketOut(
            datapath=datapath, buffer_id=datapath.ofproto.OFP_NO_BUFFER,
            in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

    def send_arp_reply(self, datapath, in_port, src_mac, src_ip, dst_mac, dst_ip):
        """Send ARP reply packet"""
        parser = datapath.ofproto_parser
        
        # Create ARP reply packet
        arp_reply = packet.Packet()
        arp_reply.add_protocol(ethernet.ethernet(ethertype=ether_types.ETH_TYPE_ARP,
                                                dst=dst_mac, src=src_mac))
        arp_reply.add_protocol(arp.arp(opcode=arp.ARP_REPLY, src_mac=src_mac, src_ip=src_ip,
                                     dst_mac=dst_mac, dst_ip=dst_ip))
        arp_reply.serialize()
        
        actions = [parser.OFPActionOutput(in_port)]
        out = parser.OFPPacketOut(datapath=datapath,
                                buffer_id=datapath.ofproto.OFP_NO_BUFFER,
                                in_port=datapath.ofproto.OFPP_CONTROLLER,
                                actions=actions, data=arp_reply.data)
        datapath.send_msg(out)

    def send_arp_request(self, datapath, dst_subnet, target_ip):
        """Broadcast an ARP request for target_ip on the destination subnet."""
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        gw_info = self.subnet_gateways.get(dst_subnet)
        if not gw_info:
            return
        gateway_ip = gw_info['gateway_ip']
        gateway_mac = gw_info['gateway_mac']

        arp_req = packet.Packet()
        arp_req.add_protocol(ethernet.ethernet(
            ethertype=ether_types.ETH_TYPE_ARP,
            dst='ff:ff:ff:ff:ff:ff',
            src=gateway_mac
        ))
        arp_req.add_protocol(arp.arp(
            opcode=arp.ARP_REQUEST,
            src_mac=gateway_mac,
            src_ip=gateway_ip,
            dst_mac='00:00:00:00:00:00',
            dst_ip=target_ip
        ))
        arp_req.serialize()

        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=ofproto.OFPP_CONTROLLER,
            actions=actions,
            data=arp_req.data
        )
        datapath.send_msg(out)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod_kwargs = {'datapath': datapath, 'priority': priority, 'match': match, 'instructions': inst}
        if buffer_id:
            mod_kwargs['buffer_id'] = buffer_id
        mod = parser.OFPFlowMod(**mod_kwargs)
        datapath.send_msg(mod)

    def _handle_gateway_ping(self, datapath, in_port, eth_pkt, ip_pkt, pkt):
        """Handle ICMP ping to gateway - respond with echo reply"""
        try:
            from ryu.lib.packet import icmp
            
            # Parse the ICMP packet
            icmp_pkt = pkt.get_protocol(icmp.icmp)
            if not icmp_pkt or icmp_pkt.type != icmp.ICMP_ECHO_REQUEST:
                self.log_activity('debug', f'Not an ICMP echo request, ignoring')
                return
            
            # Find the appropriate gateway MAC for the destination
            gateway_mac = None
            for subnet_info in self.subnet_gateways.values():
                if ip_pkt.dst == subnet_info['gateway_ip']:
                    gateway_mac = subnet_info['gateway_mac']
                    break
            
            if not gateway_mac:
                self.log_activity('warning', f'No gateway MAC found for {ip_pkt.dst}')
                return
            
            # Create ICMP echo reply
            parser = datapath.ofproto_parser
            
            # Create the reply packet
            reply_pkt = packet.Packet()
            reply_pkt.add_protocol(ethernet.ethernet(
                ethertype=ether_types.ETH_TYPE_IP,
                dst=eth_pkt.src,
                src=gateway_mac
            ))
            reply_pkt.add_protocol(ipv4.ipv4(
                dst=ip_pkt.src,
                src=ip_pkt.dst,
                proto=ip_pkt.proto
            ))
            reply_pkt.add_protocol(icmp.icmp(
                type_=icmp.ICMP_ECHO_REPLY,
                code=icmp_pkt.code,
                csum=0,
                data=icmp_pkt.data
            ))
            reply_pkt.serialize()
            
            # Send the reply
            actions = [parser.OFPActionOutput(in_port)]
            out = parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=datapath.ofproto.OFP_NO_BUFFER,
                in_port=datapath.ofproto.OFPP_CONTROLLER,
                actions=actions,
                data=reply_pkt.data
            )
            datapath.send_msg(out)
            self.log_activity('debug', f'ICMP echo reply sent to {ip_pkt.src}')
            
        except Exception as e:
            self.log_activity('warning', f'Failed to handle gateway ping: {e}')
    
    def _trigger_host_discovery(self, datapath, discovered_subnet):
        """Proactively discover hosts in other subnets"""
        expected_hosts = [
            '10.0.0.1',      # h1
            '172.16.0.2',    # h2
            '172.16.0.3',    # h3
            '172.16.0.4',    # h4
            '172.16.0.5',    # h5
            '192.168.0.6'    # h6
        ]
        
        for host_ip in expected_hosts:
            if host_ip not in self.ip_to_mac and host_ip not in self._discovered_hosts:
                host_subnet = self.get_subnet_for_ip(host_ip)
                if host_subnet and host_subnet != discovered_subnet:
                    # Send ARP request to discover this host
                    try:
                        self.log_activity('debug', f'DISCOVERY: Probing for {host_ip} in {host_subnet}')
                        self.send_arp_request(datapath, host_subnet, host_ip)
                    except Exception as e:
                        self.log_activity('warning', f'DISCOVERY: Failed to probe {host_ip}: {e}')

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        flows = []
        for stat in ev.msg.body:
            flows.append({
                'switch_id': ev.msg.datapath.id,
                'table_id': stat.table_id,
                'duration_sec': stat.duration_sec,
                'duration_nsec': stat.duration_nsec,
                'priority': stat.priority,
                'idle_timeout': stat.idle_timeout,
                'hard_timeout': stat.hard_timeout,
                'flags': stat.flags,
                'cookie': stat.cookie,
                'packet_count': stat.packet_count,
                'byte_count': stat.byte_count,
                'match': str(stat.match),
                'instructions': str(stat.instructions)
            })
        dpid = ev.msg.datapath.id
        self.flow_stats[dpid] = flows

    def _collect_stats_periodically(self):
        """Collect flow and port statistics periodically"""
        while True:
            for dpid, switch_info in self.switches.items():
                datapath = switch_info['datapath']
                self._request_stats(datapath)
            time.sleep(10)

    def _request_stats(self, datapath):
        """Request flow statistics from switch"""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)


class L3RouterAPI(ControllerBase):
    """REST API for L3 Router Controller"""
    
    def __init__(self, req, link, data, **config):
        super(L3RouterAPI, self).__init__(req, link, data, **config)
        self.controller_app = data

    @route('hello', '/hello', methods=['GET'])
    def hello(self, req, **kwargs):
        """Health check endpoint"""
        try:
            response = {"message": "Hello from Ryu L3 Router Controller!"}
            body = json.dumps(response).encode('utf-8')
            return Response(content_type='application/json; charset=utf-8', body=body)
        except Exception as e:
            error_response = {"error": str(e)}
            body = json.dumps(error_response).encode('utf-8')
            return Response(status=500, content_type='application/json; charset=utf-8', body=body)

    @route('flows', '/flows', methods=['GET'])
    def get_flows(self, req, **kwargs):
        """Get all flow statistics"""
        flows = []
        for dpid, flow_list in self.controller_app.flow_stats.items():
            flows.extend(flow_list)
        body = json.dumps(flows, indent=2).encode('utf-8')
        return Response(content_type='application/json; charset=utf-8', body=body)

    @route('activity', '/activity', methods=['GET'])
    def get_activity(self, req, **kwargs):
        """Get recent activity log"""
        body = json.dumps(self.controller_app.activity_log, indent=2).encode('utf-8')
        return Response(content_type='application/json; charset=utf-8', body=body)

    @route('subnets', '/subnets', methods=['GET'])
    def get_subnets(self, req, **kwargs):
        """Get subnet configuration"""
        body = json.dumps(self.controller_app.subnet_gateways, indent=2).encode('utf-8')
        return Response(content_type='application/json; charset=utf-8', body=body)

    @route('routing_table', '/routing_table', methods=['GET'])
    def get_routing_table(self, req, **kwargs):
        """Get routing table"""
        body = json.dumps(self.controller_app.routing_table, indent=2).encode('utf-8')
        return Response(content_type='application/json; charset=utf-8', body=body)

    @route('stats', '/stats', methods=['GET'])
    def get_stats(self, req, **kwargs):
        """Get controller statistics"""
        stats = {
            'uptime': time.time() - self.controller_app.start_time,
            'packet_count': self.controller_app.packet_count,
            'byte_count': self.controller_app.byte_count,
            'switches': len(self.controller_app.switches),
            'learned_ips': len(self.controller_app.ip_to_mac)
        }
        body = json.dumps(stats, indent=2).encode('utf-8')
        return Response(content_type='application/json; charset=utf-8', body=body)


# Create app instance
app_manager.require_app('ryu.app.wsgi')
app = L3RouterController()
