#!/usr/bin/env python2
# Minimal ONVIF PTZ device for Pepper's head, controllable from Frigate.
# Speaks just enough ONVIF (device/media/ptz, SOAP 1.2) for Frigate's
# onvif-zeep client, and maps PTZ moves to ALMotion HeadYaw/HeadPitch.
#
# Listens on :8000. Frigate camera config:
#   onvif:
#     host: 192.168.11.182
#     port: 8000
#     user: ""        # auth is ignored
#     password: ""
import os, sys, time, threading
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from SocketServer import ThreadingMixIn
import xml.etree.ElementTree as ET

# ---- redirect qi noise off stdout (keeps logs clean, same trick as cam bridge)
sys.stdout = sys.stderr
import qi

# ---------------------------------------------------------------- config
LISTEN_PORT = 8000
ADVERTISE_HOST = os.environ.get("ONVIF_HOST", "192.168.11.182")
PROFILE_TOKEN = "profile_head"
PTZ_CONFIG_TOKEN = "ptz0"
PTZ_NODE_TOKEN = "ptznode0"

# Head joint limits (rad) measured on the robot
YAW_MIN, YAW_MAX = -2.0857, 2.0857
PITCH_MIN, PITCH_MAX = -0.7069, 0.4451

# Sign mapping ONVIF velocity -> joint direction. Flip if Frigate arrows feel inverted.
YAW_SIGN = -1.0    # pan x>0 (right) -> yaw toward YAW_MIN
PITCH_SIGN = -1.0  # tilt y>0 (up)   -> pitch toward PITCH_MIN
# Fraction of each joint's max speed at velocity magnitude 1.0. Pitch needs a
# much lower factor: its travel (~1.15 rad) is far shorter than yaw's (~4.17 rad)
# while its max speed is higher, so the same factor overshoots small up/down taps.
YAW_SPEED_SCALE = 0.6
PITCH_SPEED_SCALE = 0.12
RESUME_AWARENESS_AFTER = 8.0  # seconds idle before BasicAwareness comes back
# Keep the robot awake so PTZ is instant and the aim holds. NAOqi rests the robot
# after ~30s idle (motors limp -> setAngles ignored); ALBackgroundMovement prevents
# that with negligible head drift (~0.5deg/40s). Set False for on-demand wake (robot
# rests when idle, first move re-wakes it but recenters the head).
KEEP_AWAKE = True

NS = {
    's': 'http://www.w3.org/2003/05/soap-envelope',
    'tt': 'http://www.onvif.org/ver10/schema',
    'tds': 'http://www.onvif.org/ver10/device/wsdl',
    'trt': 'http://www.onvif.org/ver10/media/wsdl',
    'tptz': 'http://www.onvif.org/ver20/ptz/wsdl',
    'timg': 'http://www.onvif.org/ver20/imaging/wsdl',
}

# ---------------------------------------------------------------- robot control
class HeadController(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.session = qi.Session()
        self.session.connect("tcp://127.0.0.1:9559")
        self.motion = self.session.service("ALMotion")
        try:
            self.ba = self.session.service("ALBasicAwareness")
        except Exception:
            self.ba = None
        try:
            self.bg = self.session.service("ALBackgroundMovement")
        except Exception:
            self.bg = None
        self.paused = False
        self.last_activity = 0.0
        self.presets = {}  # token -> (yaw, pitch)
        if KEEP_AWAKE:
            try:
                self.motion.wakeUp()
            except Exception:
                pass
            if self.bg is not None:
                try:
                    self.bg.setEnabled(True)  # prevents the ~30s idle rest
                except Exception:
                    pass
        t = threading.Thread(target=self._idle_loop)
        t.daemon = True
        t.start()

    def _prepare(self):
        # Energize motors if NAOqi put the robot to rest. When robotIsWakeUp is
        # False the joints are limp and setAngles is silently ignored -- even
        # though Head stiffness can still read 1.0 -- so we must wakeUp().
        try:
            if not self.motion.robotIsWakeUp():
                self.motion.wakeUp()
        except Exception:
            pass
        self._pause()

    def _pause(self):
        if self.ba is not None and not self.paused:
            try:
                self.ba.pauseAwareness()
                self.paused = True
            except Exception:
                pass

    def _resume(self):
        if self.ba is not None and self.paused:
            try:
                self.ba.resumeAwareness()
                self.paused = False
            except Exception:
                pass

    def _idle_loop(self):
        while True:
            time.sleep(1.0)
            if self.paused and (time.time() - self.last_activity) > RESUME_AWARENESS_AFTER:
                with self.lock:
                    self._resume()

    def continuous_move(self, vx, vy):
        with self.lock:
            self.last_activity = time.time()
            self._prepare()
            names, targets, fracs = [], [], []
            if abs(vx) > 0.01:
                target = YAW_MIN if (vx * YAW_SIGN) < 0 else YAW_MAX
                names.append("HeadYaw"); targets.append(target)
                fracs.append(min(1.0, abs(vx)) * YAW_SPEED_SCALE)
            if abs(vy) > 0.01:
                target = PITCH_MIN if (vy * PITCH_SIGN) < 0 else PITCH_MAX
                names.append("HeadPitch"); targets.append(target)
                fracs.append(min(1.0, abs(vy)) * PITCH_SPEED_SCALE)
            for n, t, f in zip(names, targets, fracs):
                self.motion.setAngles([n], [t], max(0.02, f))

    def stop(self):
        with self.lock:
            self.last_activity = time.time()
            cur = self.motion.getAngles(["HeadYaw", "HeadPitch"], True)
            self.motion.setAngles(["HeadYaw", "HeadPitch"], cur, 0.2)

    def absolute_move(self, x, y):
        # x,y in [-1,1] -> joint range
        with self.lock:
            self.last_activity = time.time()
            self._prepare()
            yaw = self._denorm(x, YAW_MIN, YAW_MAX, YAW_SIGN)
            pitch = self._denorm(y, PITCH_MIN, PITCH_MAX, PITCH_SIGN)
            self.motion.setAngles(["HeadYaw", "HeadPitch"], [yaw, pitch], 0.3)

    def goto_preset(self, token):
        if token in self.presets:
            yaw, pitch = self.presets[token]
            with self.lock:
                self.last_activity = time.time()
                self._prepare()
                self.motion.setAngles(["HeadYaw", "HeadPitch"], [yaw, pitch], 0.3)

    def set_preset(self, token):
        with self.lock:
            cur = self.motion.getAngles(["HeadYaw", "HeadPitch"], True)
            self.presets[token] = (cur[0], cur[1])

    def status(self):
        cur = self.motion.getAngles(["HeadYaw", "HeadPitch"], True)
        x = self._norm(cur[0], YAW_MIN, YAW_MAX, YAW_SIGN)
        y = self._norm(cur[1], PITCH_MIN, PITCH_MAX, PITCH_SIGN)
        return x, y

    @staticmethod
    def _norm(v, lo, hi, sign):
        n = (v - lo) / (hi - lo) * 2.0 - 1.0
        return max(-1.0, min(1.0, n * sign))

    @staticmethod
    def _denorm(n, lo, hi, sign):
        n = n * sign
        return lo + (n + 1.0) / 2.0 * (hi - lo)

CTRL = None  # set in main

# ---------------------------------------------------------------- SOAP helpers
def envelope(body):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<s:Envelope xmlns:s="%(s)s" xmlns:tt="%(tt)s" xmlns:tds="%(tds)s" '
        'xmlns:trt="%(trt)s" xmlns:tptz="%(tptz)s" xmlns:timg="%(timg)s">'
        '<s:Body>%(body)s</s:Body></s:Envelope>'
    ) % dict(NS, body=body)

def localname(tag):
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag

def XADDR(path):
    return "http://%s:%d/onvif/%s" % (ADVERTISE_HOST, LISTEN_PORT, path)

def r_GetSystemDateAndTime(root):
    t = time.gmtime()
    return (
        '<tds:GetSystemDateAndTimeResponse><tds:SystemDateAndTime>'
        '<tt:DateTimeType>Manual</tt:DateTimeType>'
        '<tt:DaylightSavings>false</tt:DaylightSavings>'
        '<tt:TimeZone><tt:TZ>UTC0</tt:TZ></tt:TimeZone>'
        '<tt:UTCDateTime>'
        '<tt:Time><tt:Hour>%d</tt:Hour><tt:Minute>%d</tt:Minute><tt:Second>%d</tt:Second></tt:Time>'
        '<tt:Date><tt:Year>%d</tt:Year><tt:Month>%d</tt:Month><tt:Day>%d</tt:Day></tt:Date>'
        '</tt:UTCDateTime></tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>'
    ) % (t.tm_hour, t.tm_min, t.tm_sec, t.tm_year, t.tm_mon, t.tm_mday)

def r_GetCapabilities(root):
    return (
        # tt:Capabilities is an ordered xsd:sequence: Analytics, Device, Events,
        # Imaging, Media, PTZ, Extension. Keep this order or zeep drops elements.
        '<tds:GetCapabilitiesResponse><tds:Capabilities>'
        '<tt:Device><tt:XAddr>%s</tt:XAddr></tt:Device>'
        '<tt:Imaging><tt:XAddr>%s</tt:XAddr></tt:Imaging>'
        '<tt:Media><tt:XAddr>%s</tt:XAddr><tt:StreamingCapabilities>'
        '<tt:RTPMulticast>false</tt:RTPMulticast><tt:RTP_TCP>true</tt:RTP_TCP>'
        '<tt:RTP_RTSP_TCP>true</tt:RTP_RTSP_TCP></tt:StreamingCapabilities></tt:Media>'
        '<tt:PTZ><tt:XAddr>%s</tt:XAddr></tt:PTZ>'
        '</tds:Capabilities></tds:GetCapabilitiesResponse>'
    ) % (XADDR('device_service'), XADDR('imaging_service'),
         XADDR('media_service'), XADDR('ptz_service'))

def r_GetServices(root):
    return (
        '<tds:GetServicesResponse>'
        '<tds:Service><tds:Namespace>%s</tds:Namespace><tds:XAddr>%s</tds:XAddr>'
        '<tds:Version><tt:Major>2</tt:Major><tt:Minor>7</tt:Minor></tds:Version></tds:Service>'
        '<tds:Service><tds:Namespace>%s</tds:Namespace><tds:XAddr>%s</tds:XAddr>'
        '<tds:Version><tt:Major>2</tt:Major><tt:Minor>7</tt:Minor></tds:Version></tds:Service>'
        '<tds:Service><tds:Namespace>%s</tds:Namespace><tds:XAddr>%s</tds:XAddr>'
        '<tds:Version><tt:Major>2</tt:Major><tt:Minor>7</tt:Minor></tds:Version></tds:Service>'
        '<tds:Service><tds:Namespace>%s</tds:Namespace><tds:XAddr>%s</tds:XAddr>'
        '<tds:Version><tt:Major>2</tt:Major><tt:Minor>7</tt:Minor></tds:Version></tds:Service>'
        '</tds:GetServicesResponse>'
    ) % (NS['tds'], XADDR('device_service'),
         NS['trt'], XADDR('media_service'),
         NS['tptz'], XADDR('ptz_service'),
         NS['timg'], XADDR('imaging_service'))

def r_GetDeviceInformation(root):
    return (
        '<tds:GetDeviceInformationResponse>'
        '<tds:Manufacturer>SoftBank Robotics</tds:Manufacturer>'
        '<tds:Model>Pepper Head</tds:Model>'
        '<tds:FirmwareVersion>2.7.1</tds:FirmwareVersion>'
        '<tds:SerialNumber>pepper-head-01</tds:SerialNumber>'
        '<tds:HardwareId>pepper</tds:HardwareId>'
        '</tds:GetDeviceInformationResponse>'
    )

def _ptz_config_xml():
    return (
        '<tt:Name>%s</tt:Name><tt:UseCount>1</tt:UseCount>'
        '<tt:NodeToken>%s</tt:NodeToken>'
        '<tt:DefaultAbsolutePantTiltPositionSpace>http://www.onvif.org/ver10/tptz/PanTiltSpaces/PositionGenericSpace</tt:DefaultAbsolutePantTiltPositionSpace>'
        '<tt:DefaultContinuousPanTiltVelocitySpace>http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace</tt:DefaultContinuousPanTiltVelocitySpace>'
        '<tt:DefaultPTZSpeed><tt:PanTilt x="1.0" y="1.0" space="http://www.onvif.org/ver10/tptz/PanTiltSpaces/GenericSpeedSpace"/></tt:DefaultPTZSpeed>'
        '<tt:DefaultPTZTimeout>PT5S</tt:DefaultPTZTimeout>'
        '<tt:PanTiltLimits><tt:Range>'
        '<tt:URI>http://www.onvif.org/ver10/tptz/PanTiltSpaces/PositionGenericSpace</tt:URI>'
        '<tt:XRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:XRange>'
        '<tt:YRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:YRange>'
        '</tt:Range></tt:PanTiltLimits>'
    ) % (PTZ_CONFIG_TOKEN, PTZ_NODE_TOKEN)

def _media_configs_xml():
    # tt:Profile is an ordered sequence: Name, VideoSourceConfiguration,
    # VideoEncoderConfiguration, ... , PTZConfiguration. Frigate drops any
    # profile lacking VideoEncoderConfiguration, so include both video configs.
    return (
        '<tt:VideoSourceConfiguration token="vsc0">'
        '<tt:Name>vsc0</tt:Name><tt:UseCount>1</tt:UseCount>'
        '<tt:SourceToken>vsrc0</tt:SourceToken>'
        '<tt:Bounds x="0" y="0" width="640" height="480"/>'
        '</tt:VideoSourceConfiguration>'
        '<tt:VideoEncoderConfiguration token="vec0">'
        '<tt:Name>vec0</tt:Name><tt:UseCount>1</tt:UseCount>'
        '<tt:Encoding>JPEG</tt:Encoding>'
        '<tt:Resolution><tt:Width>640</tt:Width><tt:Height>480</tt:Height></tt:Resolution>'
        '<tt:Quality>5.0</tt:Quality>'
        '<tt:RateControl><tt:FrameRateLimit>10</tt:FrameRateLimit>'
        '<tt:EncodingInterval>1</tt:EncodingInterval><tt:BitrateLimit>2048</tt:BitrateLimit></tt:RateControl>'
        '<tt:Multicast><tt:Address><tt:Type>IPv4</tt:Type>'
        '<tt:IPv4Address>0.0.0.0</tt:IPv4Address></tt:Address>'
        '<tt:Port>0</tt:Port><tt:TTL>1</tt:TTL><tt:AutoStart>false</tt:AutoStart></tt:Multicast>'
        '<tt:SessionTimeout>PT60S</tt:SessionTimeout>'
        '</tt:VideoEncoderConfiguration>'
    )

def _profile_inner_xml():
    return (
        '<tt:Name>head</tt:Name>%s'
        '<tt:PTZConfiguration token="%s">%s</tt:PTZConfiguration>'
    ) % (_media_configs_xml(), PTZ_CONFIG_TOKEN, _ptz_config_xml())

def r_GetProfiles(root):
    return (
        '<trt:GetProfilesResponse><trt:Profiles token="%s" fixed="true">%s'
        '</trt:Profiles></trt:GetProfilesResponse>'
    ) % (PROFILE_TOKEN, _profile_inner_xml())

def r_GetProfile(root):
    return (
        '<trt:GetProfileResponse><trt:Profile token="%s" fixed="true">%s'
        '</trt:Profile></trt:GetProfileResponse>'
    ) % (PROFILE_TOKEN, _profile_inner_xml())

def r_GetConfigurations(root):
    return (
        '<tptz:GetConfigurationsResponse><tptz:PTZConfiguration token="%s">%s'
        '</tptz:PTZConfiguration></tptz:GetConfigurationsResponse>'
    ) % (PTZ_CONFIG_TOKEN, _ptz_config_xml())

def r_GetConfiguration(root):
    return (
        '<tptz:GetConfigurationResponse><tptz:PTZConfiguration token="%s">%s'
        '</tptz:PTZConfiguration></tptz:GetConfigurationResponse>'
    ) % (PTZ_CONFIG_TOKEN, _ptz_config_xml())

def _node_xml():
    return (
        '<tt:Name>HeadNode</tt:Name>'
        '<tt:SupportedPTZSpaces>'
        '<tt:AbsolutePanTiltPositionSpace>'
        '<tt:URI>http://www.onvif.org/ver10/tptz/PanTiltSpaces/PositionGenericSpace</tt:URI>'
        '<tt:XRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:XRange>'
        '<tt:YRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:YRange>'
        '</tt:AbsolutePanTiltPositionSpace>'
        '<tt:ContinuousPanTiltVelocitySpace>'
        '<tt:URI>http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace</tt:URI>'
        '<tt:XRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:XRange>'
        '<tt:YRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:YRange>'
        '</tt:ContinuousPanTiltVelocitySpace>'
        '<tt:PanTiltSpeedSpace>'
        '<tt:URI>http://www.onvif.org/ver10/tptz/PanTiltSpaces/GenericSpeedSpace</tt:URI>'
        '<tt:XRange><tt:Min>0.0</tt:Min><tt:Max>1.0</tt:Max></tt:XRange>'
        '</tt:PanTiltSpeedSpace>'
        '</tt:SupportedPTZSpaces>'
        '<tt:MaximumNumberOfPresets>16</tt:MaximumNumberOfPresets>'
        '<tt:HomeSupported>false</tt:HomeSupported>'
    )

def r_GetNodes(root):
    return (
        '<tptz:GetNodesResponse><tptz:PTZNode token="%s">%s'
        '</tptz:PTZNode></tptz:GetNodesResponse>'
    ) % (PTZ_NODE_TOKEN, _node_xml())

def r_GetNode(root):
    return (
        '<tptz:GetNodeResponse><tptz:PTZNode token="%s">%s'
        '</tptz:PTZNode></tptz:GetNodeResponse>'
    ) % (PTZ_NODE_TOKEN, _node_xml())

def r_GetConfigurationOptions(root):
    return (
        '<tptz:GetConfigurationOptionsResponse><tptz:PTZConfigurationOptions>'
        '<tt:Spaces>'
        '<tt:AbsolutePanTiltPositionSpace>'
        '<tt:URI>http://www.onvif.org/ver10/tptz/PanTiltSpaces/PositionGenericSpace</tt:URI>'
        '<tt:XRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:XRange>'
        '<tt:YRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:YRange>'
        '</tt:AbsolutePanTiltPositionSpace>'
        '<tt:ContinuousPanTiltVelocitySpace>'
        '<tt:URI>http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace</tt:URI>'
        '<tt:XRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:XRange>'
        '<tt:YRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:YRange>'
        '</tt:ContinuousPanTiltVelocitySpace>'
        '</tt:Spaces>'
        '<tt:PTZTimeout><tt:Min>PT1S</tt:Min><tt:Max>PT10S</tt:Max></tt:PTZTimeout>'
        '</tptz:PTZConfigurationOptions></tptz:GetConfigurationOptionsResponse>'
    )

def r_GetImagingSettings(root):
    return ('<timg:GetImagingSettingsResponse><timg:ImagingSettings>'
            '</timg:ImagingSettings></timg:GetImagingSettingsResponse>')

def r_GetOptions(root):
    return ('<timg:GetOptionsResponse><timg:ImagingOptions>'
            '</timg:ImagingOptions></timg:GetOptionsResponse>')

def r_GetMoveOptions(root):
    # no focus move support -> empty MoveOptions
    return '<timg:GetMoveOptionsResponse><timg:MoveOptions/></timg:GetMoveOptionsResponse>'

def r_GetStatus(root):
    # GetStatus exists for both PTZ (tptz) and Imaging (timg)
    if _op_namespace(root) == NS['timg']:
        return '<timg:GetStatusResponse><timg:Status/></timg:GetStatusResponse>'
    x, y = CTRL.status()
    return (
        '<tptz:GetStatusResponse><tptz:PTZStatus>'
        '<tt:Position>'
        '<tt:PanTilt x="%.4f" y="%.4f" space="http://www.onvif.org/ver10/tptz/PanTiltSpaces/PositionGenericSpace"/>'
        '<tt:Zoom x="0.0" space="http://www.onvif.org/ver10/tptz/ZoomSpaces/PositionGenericSpace"/>'
        '</tt:Position>'
        '<tt:MoveStatus><tt:PanTilt>IDLE</tt:PanTilt><tt:Zoom>IDLE</tt:Zoom></tt:MoveStatus>'
        '<tt:UtcTime>%s</tt:UtcTime>'
        '</tptz:PTZStatus></tptz:GetStatusResponse>'
    ) % (x, y, time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))

def _find_panTilt(root):
    for el in root.iter():
        if localname(el.tag) == 'PanTilt':
            return float(el.get('x', '0') or 0), float(el.get('y', '0') or 0)
    return 0.0, 0.0

def _find_text(root, name):
    for el in root.iter():
        if localname(el.tag) == name and el.text:
            return el.text.strip()
    return None

def r_ContinuousMove(root):
    x, y = _find_panTilt(root)
    CTRL.continuous_move(x, y)
    return '<tptz:ContinuousMoveResponse/>'

def r_Stop(root):
    CTRL.stop()
    return '<tptz:StopResponse/>'

def r_AbsoluteMove(root):
    x, y = _find_panTilt(root)
    CTRL.absolute_move(x, y)
    return '<tptz:AbsoluteMoveResponse/>'

def r_RelativeMove(root):
    x, y = _find_panTilt(root)
    # treat as a nudge via continuous move pulse
    CTRL.continuous_move(x, y)
    time.sleep(0.3)
    CTRL.stop()
    return '<tptz:RelativeMoveResponse/>'

def r_GetPresets(root):
    items = ''
    for tok, (yaw, pitch) in CTRL.presets.items():
        items += ('<tptz:Preset token="%s"><tt:Name>%s</tt:Name></tptz:Preset>' % (tok, tok))
    return '<tptz:GetPresetsResponse>%s</tptz:GetPresetsResponse>' % items

def r_SetPreset(root):
    tok = _find_text(root, 'PresetToken') or ('preset%d' % (len(CTRL.presets) + 1))
    CTRL.set_preset(tok)
    return '<tptz:SetPresetResponse><tptz:PresetToken>%s</tptz:PresetToken></tptz:SetPresetResponse>' % tok

def r_GotoPreset(root):
    tok = _find_text(root, 'PresetToken')
    if tok:
        CTRL.goto_preset(tok)
    return '<tptz:GotoPresetResponse/>'

def r_RemovePreset(root):
    tok = _find_text(root, 'PresetToken')
    if tok in CTRL.presets:
        del CTRL.presets[tok]
    return '<tptz:RemovePresetResponse/>'

def r_GetVideoSources(root):
    return ('<trt:GetVideoSourcesResponse>'
            '<trt:VideoSources token="vsrc0"><tt:Framerate>10</tt:Framerate>'
            '<tt:Resolution><tt:Width>640</tt:Width><tt:Height>480</tt:Height></tt:Resolution>'
            '</trt:VideoSources></trt:GetVideoSourcesResponse>')

def _op_namespace(root):
    for el in root.iter():
        if localname(el.tag) == 'Body':
            ch = list(el)
            if ch and '}' in ch[0].tag:
                return ch[0].tag.split('}', 1)[0][1:]
    return ''

def r_GetServiceCapabilities(root):
    ns = _op_namespace(root)
    if ns == NS['tptz']:
        return ('<tptz:GetServiceCapabilitiesResponse><tptz:Capabilities '
                'EFlip="false" Reverse="false" GetCompatibleConfigurations="false" '
                'MoveStatus="true" StatusPosition="true"/></tptz:GetServiceCapabilitiesResponse>')
    if ns == NS['trt']:
        return ('<trt:GetServiceCapabilitiesResponse><trt:Capabilities '
                'SnapshotUri="false" Rotation="false" VideoSourceMode="false" '
                'OSD="false"/></trt:GetServiceCapabilitiesResponse>')
    if ns == NS['timg']:
        return ('<timg:GetServiceCapabilitiesResponse><timg:Capabilities '
                'ImageStabilization="false"/></timg:GetServiceCapabilitiesResponse>')
    return ('<tds:GetServiceCapabilitiesResponse><tds:Capabilities>'
            '<tds:Network IPFilter="false" DynDNS="false"/>'
            '<tds:System DiscoveryResolve="false" DiscoveryBye="false"/>'
            '</tds:Capabilities></tds:GetServiceCapabilitiesResponse>')

DISPATCH = {
    'GetSystemDateAndTime': r_GetSystemDateAndTime,
    'GetServiceCapabilities': r_GetServiceCapabilities,
    'GetCapabilities': r_GetCapabilities,
    'GetServices': r_GetServices,
    'GetDeviceInformation': r_GetDeviceInformation,
    'GetProfiles': r_GetProfiles,
    'GetProfile': r_GetProfile,
    'GetVideoSources': r_GetVideoSources,
    'GetConfigurations': r_GetConfigurations,
    'GetConfiguration': r_GetConfiguration,
    'GetConfigurationOptions': r_GetConfigurationOptions,
    'GetNodes': r_GetNodes,
    'GetNode': r_GetNode,
    'GetStatus': r_GetStatus,
    'GetImagingSettings': r_GetImagingSettings,
    'GetOptions': r_GetOptions,
    'GetMoveOptions': r_GetMoveOptions,
    'ContinuousMove': r_ContinuousMove,
    'Stop': r_Stop,
    'AbsoluteMove': r_AbsoluteMove,
    'RelativeMove': r_RelativeMove,
    'GetPresets': r_GetPresets,
    'SetPreset': r_SetPreset,
    'GotoPreset': r_GotoPreset,
    'RemovePreset': r_RemovePreset,
}

def fault(msg):
    return envelope(
        '<s:Fault xmlns:s="%s"><s:Code><s:Value>s:Receiver</s:Value></s:Code>'
        '<s:Reason><s:Text xml:lang="en">%s</s:Text></s:Reason></s:Fault>' % (NS['s'], msg))

# ---------------------------------------------------------------- HTTP server
class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else ''
        op = '?'
        try:
            root = ET.fromstring(body)
            # operation = first child of soap Body
            op = None
            for el in root.iter():
                if localname(el.tag) == 'Body':
                    children = list(el)
                    if children:
                        op = localname(children[0].tag)
                    break
            ua = self.headers.get('User-Agent', '?')
            sys.stderr.write("ONVIF REQ from %s op=%s ua=%s\n" % (self.client_address[0], op, ua))
            handler = DISPATCH.get(op)
            if handler is None:
                sys.stderr.write("ONVIF: UNHANDLED op %r from %s\n" % (op, self.client_address[0]))
                payload = fault('Unhandled operation: %s' % op)
            else:
                payload = envelope(handler(root))
            # debug: dump last request/response for offline inspection
            try:
                with open('/data/onvif/last_%s.xml' % (op or 'none'), 'wb') as f:
                    f.write(b'<!-- REQUEST -->\n'); f.write(body if isinstance(body, bytes) else body.encode('utf-8'))
                    f.write(b'\n<!-- RESPONSE -->\n'); f.write(payload.encode('utf-8'))
            except Exception:
                pass
        except Exception as e:
            sys.stderr.write("ONVIF: error on %r: %s\n" % (op, e))
            payload = fault(str(e))
        data = payload.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/soap+xml; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write('ok')

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

def main():
    global CTRL
    CTRL = HeadController()
    srv = ThreadingHTTPServer(('0.0.0.0', LISTEN_PORT), Handler)
    sys.stderr.write("ONVIF PTZ server listening on :%d (advertise %s)\n" % (LISTEN_PORT, ADVERTISE_HOST))
    srv.serve_forever()

if __name__ == '__main__':
    main()
