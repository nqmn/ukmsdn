#!/usr/bin/env python3
"""
Ryu Controller Application with REST API for Flow Monitor
This application provides OpenFlow switching functionality with REST APIs
for the web-based flow monitor to connect and retrieve real-time data.
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

# Import standardized logging (with fallback for Ryu environment)
try:
    from ..utils.logger import get_controller_logger
except ImportError:
    try:
        from utils.logger import get_controller_logger
    except ImportError:
        # Fallback - use Ryu's built-in logger
        def get_controller_logger(log_dir=None):
            import logging
            return logging.getLogger('ryu.app.FlowMonitorController')

class FlowMonitorController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(FlowMonitorController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.switches = {}
        self.links = {}
        self.flow_stats = defaultdict(dict)
        self.port_stats = defaultdict(dict)
        self.activity_log = []
        self.start_time = time.time()
        self.packet_count = 0
        self.byte_count = 0

        if 'wsgi' in kwargs:
            wsgi = kwargs['wsgi']
            wsgi.register(FlowMonitorAPI, self)
        else:
            self.logger.warning("WSGI context not provided to FlowMonitorController. REST API will not be available.")

        # Initialize standardized logging (falls back to Ryu logger)
        try:
            self.std_logger = get_controller_logger()
        except:
            self.std_logger = self.logger
            
        self.stats_thread = threading.Thread(target=self._collect_stats_periodically)
        self.stats_thread.daemon = True
        self.stats_thread.start()
        self.log_activity('info', 'Ryu Flow Monitor Controller started')
        self.std_logger.info('Ryu Flow Monitor Controller started')

        

    def log_activity(self, level, message):
        timestamp = datetime.now().strftime('%H:%M:%S')
        entry = {'timestamp': timestamp, 'level': level, 'message': message}
        self.activity_log.append(entry)
        if len(self.activity_log) > 100:
            self.activity_log.pop(0)
        self.logger.info(f"[{level.upper()}] {message}")

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

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        self.log_activity('info', f'Switch {hex(dpid)} connected')

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

        out_port = self.mac_to_port[dpid].get(dst, ofproto.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, 1, match, actions, msg.buffer_id)
            else:
                self.add_flow(datapath, 1, match, actions)

        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None, idle_timeout=30, hard_timeout=300):
        """Add flow with explicit timeouts to ensure flow capture guarantees"""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod_kwargs = {
            'datapath': datapath, 
            'priority': priority, 
            'match': match, 
            'instructions': inst,
            'idle_timeout': idle_timeout,  # Keep flow for 30s after last packet
            'hard_timeout': hard_timeout   # Maximum flow lifetime of 5 minutes
        }
        if buffer_id:
            mod_kwargs['buffer_id'] = buffer_id
        mod = parser.OFPFlowMod(**mod_kwargs)
        datapath.send_msg(mod)
        
        # Log flow installation for monitoring
        self.log_activity('debug', f'Flow installed: priority={priority}, idle_timeout={idle_timeout}s, hard_timeout={hard_timeout}s')

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        flows = []
        for stat in ev.msg.body:
            flows.append({
                'priority': stat.priority,
                'match': str(stat.match),
                'actions': str(stat.instructions),
                'packet_count': stat.packet_count,
                'byte_count': stat.byte_count,
                'duration_sec': stat.duration_sec
            })
        self.flow_stats[ev.msg.datapath.id] = flows

    def _collect_stats_periodically(self):
        while True:
            try:
                for switch_info in self.switches.values():
                    self._request_stats(switch_info['datapath'])
                time.sleep(2)
            except Exception as e:
                self.logger.error(f"Error collecting stats: {e}")
                time.sleep(2)

    def _request_stats(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        datapath.send_msg(parser.OFPFlowStatsRequest(datapath))
        datapath.send_msg(parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY))

    def get_flow_stats_all(self):
        all_flows = []
        for dpid, flows in self.flow_stats.items():
            for flow in flows:
                flow['switch_id'] = hex(dpid)
                all_flows.append(flow)
        return all_flows

class FlowMonitorAPI(ControllerBase):

    def __init__(self, req, link, data, **config):
        super().__init__(req, link, data, **config)
        self.controller = data

    @route('api', '/flows', methods=['GET'])
    def list_flows(self, req, **kwargs):
        body = json.dumps(self.controller.get_flow_stats_all()).encode('utf-8')
        return Response(content_type='application/json', body=body)

    @route('api', '/flows/{dpid}', methods=['GET'])
    def get_dpid_flows(self, req, dpid, **kwargs):
        try:
            dpid_int = int(dpid, 16)
            if dpid_int not in self.controller.flow_stats:
                return Response(status=404)
            body = json.dumps(self.controller.flow_stats[dpid_int]).encode('utf-8')
            return Response(content_type='application/json', body=body)
        except (ValueError, KeyError):
            return Response(status=400)

    @route('api', '/hello', methods=['GET'])
    def hello_world(self, req, **kwargs):
        body = json.dumps({"message": "Hello from Ryu Controller!"}).encode('utf-8')
        return Response(content_type='application/json', body=body)

    @route('api', '/topology/switches', methods=['GET'])
    def list_switches(self, req, **kwargs):
        switches = get_switch(self.controller)
        body = json.dumps([s.to_dict() for s in switches]).encode('utf-8')
        return Response(content_type='application/json', body=body)

    @route('api', '/topology/links', methods=['GET'])
    def list_links(self, req, **kwargs):
        links = get_link(self.controller)
        body = json.dumps([l.to_dict() for l in links]).encode('utf-8')
        return Response(content_type='application/json', body=body)

    @route('api', '/topology/hosts', methods=['GET'])
    def list_hosts(self, req, **kwargs):
        hosts = get_host(self.controller)
        body = json.dumps([h.to_dict() for h in hosts]).encode('utf-8')
        return Response(content_type='application/json', body=body)
