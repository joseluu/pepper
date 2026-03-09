"use strict";

const VERSION = "vigibot 2.0";

const USER = require("/home/nao/robot.json");
const SYS = require("./sys.json");

const FRAME = require("./trame.js");

const OS = require("os");
const FS = require("fs");
const IO = require("socket.io-client");
const IO_LEGACY = require("socket.io-client-legacy");
const EXEC = require("child_process").exec;
const RL = require("readline");
const NET = require("net");
const SPLIT = require("stream-split");

const FRAME0 = "$".charCodeAt();
const FRAME1S = "S".charCodeAt();
const FRAME1T = "T".charCodeAt();

const PROCESSTIME = Date.now();
const OSTIME = PROCESSTIME - OS.uptime() * 1000;

let sockets = {};
let currentServer = "";

let up = false;
let engine = false;
let upTimeout;

let initDone = false;
let initVideo = false;
let initNaoqi = false;
let naoqiSocket = null;

let conf = {};
let hard = {};
let tx;
let rx;
let confVideo;
let oldConfVideo;
let cmdDiffusion;
let cmdDiffAudio;

let lastTimestamp = Date.now();
let lastFrame = Date.now();
let latencyAlarm = false;

let floatTargets16 = [];
let floatTargets8 = [];
let floatTargets1 = [];
let floatCommands16 = [];
let floatCommands8 = [];
let floatCommands1 = [];
let margins16 = [];
let margins8 = [];

let oldOutputs = [];
let backslashs = [];

let voltage = 0;
let battery = 0;
let cpuLoad = 0;
let socTemp = 0;
let link = 0;
let rssi = 0;

let naoqiSession = null;
let motionProxy = null;
let batteryProxy = null;
let ttsProxy = null;

if(typeof USER.SERVERS === "undefined")
 USER.SERVERS = SYS.SERVERS;

if(typeof USER.CMDDIFFUSION === "undefined")
 USER.CMDDIFFUSION = SYS.CMDDIFFUSION;

if(typeof USER.CMDDIFFAUDIO === "undefined")
 USER.CMDDIFFAUDIO = SYS.CMDDIFFAUDIO;

if(typeof USER.CMDTTS === "undefined")
 USER.CMDTTS = SYS.CMDTTS;

USER.SERVERS.forEach(function(server) {
 sockets[server] = IO.connect(server, {"connect timeout": 1000, transports: ["websocket"], path: "/" + SYS.SECUREMOTEPORT + "/socket.io"});
});

hard.DEBUG = true;
hard.TELEDEBUG = false;

trace("Pepper client start", true);

function setInit() {
 initDone = initNaoqi && initVideo;
}

function map(n, inMin, inMax, outMin, outMax) {
 return Math.trunc((n - inMin) * (outMax - outMin) / (inMax - inMin) + outMin);
}

function hmsm(date) {
 return ("0" + date.getHours()).slice(-2) + ":" +
        ("0" + date.getMinutes()).slice(-2) + ":" +
        ("0" + date.getSeconds()).slice(-2) + ":" +
        ("00" + date.getMilliseconds()).slice(-3);
}

function trace(message, mandatory) {
 if(mandatory || hard.DEBUG) {
  let trace = hmsm(new Date()) + " | " + message;
  FS.appendFile(SYS.LOGFILE, trace + "\n", function(err) {
  });
 }

 if(mandatory || hard.TELEDEBUG) {
  USER.SERVERS.forEach(function(server) {
   sockets[server].emit("serveurrobottrace", message);
  });
 }
}

function traces(id, messages, mandatory) {
 if(!hard.DEBUG && !hard.TELEDEBUG)
  return;

 let array = messages.split("\n");
 if(!array[array.length - 1])
  array.pop();
 for(let i = 0; i < array.length; i++)
  trace(id + " | " + array[i], mandatory);
}

function constrain(n, nMin, nMax) {
 if(n > nMax)
  n = nMax;
 else if(n < nMin)
  n = nMin;

 return n;
}

function sigterm(name, process, callback) {
 trace("Sending the SIGTERM signal to the process " + name, false);
 let processkill = EXEC("/usr/bin/pkill -15 -f ^" + process);
 processkill.on("close", function(code) {
  callback(code);
 });
}

function exec(name, command, callback) {
 trace("Starting the process " + name, false);
 trace(command, false);
 let proc = EXEC(command);
 let stdout = RL.createInterface(proc.stdout);
 let stderr = RL.createInterface(proc.stderr);
 let pid = proc.pid;
 let execTime = Date.now();

 stdout.on("line", function(data) {
  traces(name + " | " + pid + " | stdout", data);
 });

 stderr.on("line", function(data) {
  traces(name + " | " + pid + " | stderr", data);
 });

 proc.on("close", function(code) {
  let elapsed = Date.now() - execTime;
  trace("The " + name + " process is stopped after " + elapsed + " milliseconds with the exit code " + code, false);
  callback(code);
 });
}

// naoqiCall uses the v1.0 protocol: params.obj, params.method, params.args
// For ServiceDirectory.service, obj="ServiceDirectory", method="service"
// For service methods, obj=pyobject ID (number), method=method name
function naoqiCall(obj, method, args) {
 return new Promise(function(resolve, reject) {
  if(!naoqiSocket) {
   reject(new Error("NAOqi not connected"));
   return;
  }

  let idm = Math.floor(Math.random() * 1000000);

  naoqiSocket.emit('call', {
   idm: idm,
   params: {
    obj: obj,
    method: method,
    args: args
   }
  });

  let timeout = setTimeout(function() {
   naoqiSocket.removeListener('reply', onReply);
   naoqiSocket.removeListener('error', onError);
   reject(new Error("NAOqi call timeout: " + obj + "." + method));
  }, 30000);

  function onReply(data) {
   if(data.idm === idm) {
    clearTimeout(timeout);
    naoqiSocket.removeListener('reply', onReply);
    naoqiSocket.removeListener('error', onError);
    trace("NAOqi reply for " + obj + "." + method, false);
    resolve(data.result);
   }
  }

  function onError(data) {
   if(data && data.idm === idm) {
    clearTimeout(timeout);
    naoqiSocket.removeListener('reply', onReply);
    naoqiSocket.removeListener('error', onError);
    trace("NAOqi error: " + obj + "." + method + ": " + JSON.stringify(data.result), true);
    reject(new Error(data.result.error || data.result || "NAOqi error"));
   }
  }

  naoqiSocket.on('reply', onReply);
  naoqiSocket.on('error', onError);
 });
}

function connectNaoqi() {
 return new Promise(function(resolve, reject) {
  let host = SYS.NAOQIBRIDGE || "127.0.0.1";
  let port = SYS.NAOQIBRIDGEPORT || 80;
  let path = SYS.NAOQIPATH || "libs/qimessaging/1.0/socket.io";

  trace("Connecting to NAOqi bridge at http://" + host + ":" + port + " with resource " + path, true);

  naoqiSocket = IO_LEGACY.connect("http://" + host + ":" + port, {
   "connect timeout": 5000,
   transports: ["xhr-polling", "websocket"],
   resource: path
  });

  naoqiSocket.on("connect", function() {
   trace("Connected to NAOqi bridge", true);

   // ServiceDirectory.service returns {pyobject: N, metaobject: {...}}
   // Subsequent calls use the pyobject ID as obj
   naoqiCall("ServiceDirectory", "service", ["ALMotion"]).then(function(result) {
    motionProxy = result.pyobject;
    trace("ALMotion service acquired (pyobject=" + motionProxy + ")", true);
    return naoqiCall(motionProxy, "wakeUp", []).catch(function(err) {
     trace("wakeUp warning (non-fatal): " + err.message, true);
    });
   }).then(function() {
    trace("Robot woken up", true);
    return naoqiCall("ServiceDirectory", "service", ["ALBattery"]);
   }).then(function(result) {
    batteryProxy = result.pyobject;
    trace("ALBattery service acquired (pyobject=" + batteryProxy + ")", true);
    return naoqiCall("ServiceDirectory", "service", ["ALTextToSpeech"]);
   }).then(function(result) {
    ttsProxy = result.pyobject;
    trace("ALTextToSpeech service acquired (pyobject=" + ttsProxy + ")", true);
    initNaoqi = true;
    setInit();
    resolve();
   }).catch(function(err) {
    trace("NAOqi init error: " + (err ? err.message : 'undefined') + " | stack: " + (err && err.stack), true);
    reject(err);
   });
  });

  naoqiSocket.on("error", function(err) {
   trace("NAOqi bridge socket error: " + (err ? JSON.stringify(err) : 'undefined err'), true);
  });

  naoqiSocket.on("disconnect", function() {
   trace("NAOqi bridge disconnected", true);
   initNaoqi = false;
   setInit();
  });
 });
}

function applyMotorCommands() {
 if(!motionProxy || !initDone)
  return;
 
 let jointNames = [];
 let jointAngles = [];
 let speed = 0.3;
 
 for(let i = 0; i < conf.TX.COMMANDS16.length; i++) {
  let jointName = hard.COMMANDS16[i].JOINT;
  if(jointName) {
   let angle = floatCommands16[i];
   jointNames.push(jointName);
   jointAngles.push(angle);
  }
 }
 
 if(jointNames.length > 0) {
  naoqiCall(motionProxy, "setAngles", [jointNames, jointAngles, speed]).catch(function(err) {
   trace("Motor command error: " + err.message, false);
  });
 }
}

function speak(text) {
 if(!ttsProxy || !initDone)
  return;
 
 naoqiCall(ttsProxy, "say", [text]).catch(function(err) {
  trace("TTS error: " + err.message, false);
 });
}

function wake(server) {
 if(up)
  return;

 if(!initDone) {
  trace("This robot is not initialized", true);
  return;
 }

 if(currentServer) {
  trace("This robot is already in use from the " + currentServer + " server", true);
  return;
 }

 trace("Robot wake", false);

 if(hard.SNAPSHOTSINTERVAL) {
  sigterm("ffmpeg", "ffmpeg.*video", function(code) {
   diffusion();
  });
 } else
  diffusion();
 
 currentServer = server;
 up = true;
 engine = true;
}

function sigterms(callback) {
 let i = 0;

 function loop() {
  if(i == USER.CMDDIFFUSION.length) {
   callback();
   return;
  }
  sigterm("Diffusion" + i, USER.CMDDIFFUSION[i][0], loop);
  i++;
 }

 loop();
}

function sleep() {
 if(!up)
  return;

 trace("Robot sleep", false);

 for(let i = 0; i < conf.TX.COMMANDS16.length; i++)
  if(hard.COMMANDS16[i].SLEEP)
   floatTargets16[i] = conf.TX.COMMANDS16[i].INIT;

 for(let i = 0; i < conf.TX.COMMANDS8.length; i++)
  if(hard.COMMANDS8[i].SLEEP)
   floatTargets8[i] = conf.TX.COMMANDS8[i].INIT;

 for(let i = 0; i < conf.TX.COMMANDS1.length; i++)
  if(hard.COMMANDS1[i].SLEEP)
   floatTargets1[i] = conf.TX.COMMANDS1[i].INIT;

 sigterms(function() {
 });

 if(motionProxy) {
  naoqiCall(motionProxy, "rest", []).catch(function() {});
 }

 currentServer = "";
 up = false;
}

function configurationVideo(callback) {
 cmdDiffusion = USER.CMDDIFFUSION[confVideo.SOURCE].join("").replace(new RegExp("WIDTH", "g"), confVideo.WIDTH
                                                           ).replace(new RegExp("HEIGHT", "g"), confVideo.HEIGHT
                                                           ).replace(new RegExp("FPS", "g"), confVideo.FPS
                                                           ).replace(new RegExp("BITRATE", "g"), confVideo.BITRATE
                                                           ).replace(new RegExp("ROTATE", "g"), confVideo.ROTATE
                                                           ).replace(new RegExp("VIDEOLOCALPORT", "g"), SYS.VIDEOLOCALPORT);
 cmdDiffAudio = USER.CMDDIFFAUDIO.join("").replace(new RegExp("RECORDINGDEVICE", "g"), hard.RECORDINGDEVICE
                                         ).replace(new RegExp("AUDIOLOCALPORT", "g"), SYS.AUDIOLOCALPORT);

 trace("Initializing the Pepper camera configuration", false);

 callback();
}

function diffusion() {
 trace("Starting the H.264 video broadcast stream", false);
 exec("Diffusion", cmdDiffusion, function() {
  trace("Stopping the H.264 video broadcast stream", false);
 });
}

function actions(trx) {
 for(let i = 0; i < conf.TX.COMMANDS16.length; i++)
  floatTargets16[i] = trx.getFloatCommand16(i);

 for(let i = 0; i < conf.TX.COMMANDS8.length; i++)
  floatTargets8[i] = trx.getFloatCommand8(i);

 for(let i = 0; i < conf.TX.COMMANDS1.length; i++)
  floatTargets1[i] = trx.getCommand1(i);
}

function initOutputs() {
 for(let i = 0; i < conf.TX.COMMANDS16.length; i++) {
  floatTargets16[i] = conf.TX.COMMANDS16[i].INIT;
  floatCommands16[i] = floatTargets16[i];
  margins16[i] = (conf.TX.COMMANDS16[i].SCALEMAX - conf.TX.COMMANDS16[i].SCALEMIN) / 65535;
 }

 for(let i = 0; i < conf.TX.COMMANDS8.length; i++) {
  floatTargets8[i] = conf.TX.COMMANDS8[i].INIT;
  floatCommands8[i] = floatTargets8[i];
  margins8[i] = (conf.TX.COMMANDS8[i].SCALEMAX - conf.TX.COMMANDS8[i].SCALEMIN) / 255;
 }

 for(let i = 0; i < conf.TX.COMMANDS1.length; i++) {
  floatTargets1[i] = conf.TX.COMMANDS1[i].INIT;
  floatCommands1[i] = floatTargets1[i];
 }

 for(let i = 0; i < hard.OUTPUTS.length; i++) {
  oldOutputs[i] = 0;
  backslashs[i] = 0;
 }
}

USER.SERVERS.forEach(function(server, index) {

 sockets[server].on("connect", function() {
  trace("Connected to " + server + "/" + SYS.SECUREMOTEPORT, true);
  EXEC("hostname -I 2>/dev/null || echo unknown", function(err, ipPriv) {
   EXEC("iwgetid -r 2>/dev/null || echo unknown", function(err2, ssid) {
    sockets[server].emit("serveurrobotlogin", {
     conf: USER,
     version: VERSION,
     processTime: PROCESSTIME,
     osTime: OSTIME,
     ipPriv: (ipPriv || "").trim(),
     ssid: (ssid || "").trim()
    });
    trace("Login sent to " + server, true);
   });
  });
 });

 if(index == 0) {
  sockets[server].on("clientsrobotconf", function(data) {
   trace("Receiving robot configuration data from the " + server + " server", true);

   const CMDINT = RegExp(/^-?\d{1,10}$/);
   for(let i = 0; i < data.hard.CAMERAS.length; i++) {
    if(!(CMDINT.test(data.hard.CAMERAS[i].SOURCE) &&
         CMDINT.test(data.hard.CAMERAS[i].WIDTH) &&
         CMDINT.test(data.hard.CAMERAS[i].HEIGHT) &&
         CMDINT.test(data.hard.CAMERAS[i].FPS) &&
         CMDINT.test(data.hard.CAMERAS[i].BITRATE) &&
         CMDINT.test(data.hard.CAMERAS[i].ROTATE) &&
         CMDINT.test(data.hard.CAMERAS[i].BRIGHTNESS) &&
         CMDINT.test(data.hard.CAMERAS[i].CONTRAST) &&
         CMDINT.test(data.hard.CAMERAS[i].BRIGHTNESSBOOST) &&
         CMDINT.test(data.hard.CAMERAS[i].CONTRASTBOOST)))
     return;
   }
   if(!(CMDINT.test(data.hard.WLANDEVICE) ||
        data.hard.WLANDEVICE === SYS.UNUSED) &&
        CMDINT.test(data.hard.RECORDINGDEVICE))
    return;

   conf = data.conf;
   hard = data.hard;

   tx = new FRAME.Tx(conf.TX);
   rx = new FRAME.Rx(conf.TX, conf.RX);

   confVideo = hard.CAMERAS[conf.COMMANDS[conf.DEFAULTCOMMAND].CAMERA];
   oldConfVideo = confVideo;

   initOutputs();
   if(!up)
    writeOutputs();

   setTimeout(function() {
    if(!up)
     setSleepModes();
   }, 100);

   setTimeout(function() {
    if(up) {
     sigterms(function() {
      configurationVideo(function() {
       diffusion();
      });
     });
    } else {
     configurationVideo(function() {
      initVideo = true;
      setInit();
     });
    }
   }, 200);

  });
 }

 sockets[server].on("disconnect", function() {
  trace("Disconnected from " + server + "/" + SYS.SECUREMOTEPORT, true);
  sleep();
 });

 sockets[server].on("connect_error", function(err) {
  trace("Connection error to " + server + ": " + (err ? JSON.stringify(err) : 'unknown'), true);
 });

 sockets[server].on("clientsrobottts", function(data) {
  speak(data);
 });

 sockets[server].on("clientsrobotsys", function(data) {
  switch(data) {
   case "exit":
    trace("Restart the client process", true);
    process.exit();
    break;
   case "reboot":
    trace("Restart the system", true);
    setTimeout(function() {
     EXEC("reboot");
    }, 1000);
    setTimeout(function() {
     trace("Emergency reboot using SysRq", true);
    }, 9000);
    setTimeout(function() {
     EXEC("echo b > /proc/sysrq-trigger");
    }, 10000);
    break;
   case "poweroff":
    trace("Power off the system", true);
    EXEC("poweroff");
    break;
  }
 });

 sockets[server].on("echo", function(data) {
  sockets[server].emit("echo", {
   serveur: data,
   client: Date.now()
  });
 });

 sockets[server].on("clientsrobottx", function(data) {
  if(currentServer && server != currentServer || !initDone)
   return;

  if(data.data[0] != FRAME0 ||
     data.data[1] != FRAME1S &&
     data.data[1] != FRAME1T) {
   trace("Reception of a corrupted frame", false);
   return;
  }

  let now = Date.now();
  if(now - lastFrame < SYS.TXRATE / 2)
   return;
  lastFrame = now;

  lastTimestamp = data.boucleVideoCommande;

  if(data.data[1] == FRAME1S) {
   for(let i = 0; i < tx.byteLength; i++)
    tx.bytes[i] = data.data[i];

   actions(tx);

   confVideo = hard.CAMERAS[tx.cameraChoices[0]];
   if(confVideo != oldConfVideo &&
      JSON.stringify(confVideo) != JSON.stringify(oldConfVideo)) {
    if(up) {
     sigterms(function() {
      configurationVideo(function() {
       diffusion();
      });
     });
    } else {
     configurationVideo(function() {
     });
    }
    oldConfVideo = confVideo;
   }

  } else
   trace("Reception of a text frame", false);

  wake(server);
  clearTimeout(upTimeout);
  upTimeout = setTimeout(function() {
   sleep();
  }, SYS.UPTIMEOUT);

  setRxCommands();
  setRxValues();
  sockets[server].emit("serveurrobotrx", {
   timestamp: now,
   data: rx.arrayBuffer
  });
 });
});

function computeOut(n, value) {
 let out;
 let nbInMax = hard.OUTPUTS[n].INS.length - 1;

 if(value <= hard.OUTPUTS[n].INS[0])
  out = hard.OUTPUTS[n].OUTS[0];
 else if(value > hard.OUTPUTS[n].INS[nbInMax])
  out = hard.OUTPUTS[n].OUTS[nbInMax];
 else {
  for(let i = 0; i < nbInMax; i++) {
   if(value <= hard.OUTPUTS[n].INS[i + 1]) {
    out = map(value, hard.OUTPUTS[n].INS[i], hard.OUTPUTS[n].INS[i + 1], hard.OUTPUTS[n].OUTS[i], hard.OUTPUTS[n].OUTS[i + 1]);
    break;
   }
  }
 }

 return out;
}

function writeOutputs() {
 for(let i = 0; i < hard.OUTPUTS.length; i++) {

  let output = 0;

  for(let j = 0; j < hard.OUTPUTS[i].COMMANDS16.length; j++)
   output += floatCommands16[hard.OUTPUTS[i].COMMANDS16[j]] * hard.OUTPUTS[i].GAINS16[j];
  for(let j = 0; j < hard.OUTPUTS[i].COMMANDS8.length; j++)
   output += floatCommands8[hard.OUTPUTS[i].COMMANDS8[j]] * hard.OUTPUTS[i].GAINS8[j];
  for(let j = 0; j < hard.OUTPUTS[i].COMMANDS1.length; j++)
   output += floatCommands1[hard.OUTPUTS[i].COMMANDS1[j]] * hard.OUTPUTS[i].GAINS1[j];

  if(output < oldOutputs[i])
   backslashs[i] = -hard.OUTPUTS[i].BACKSLASH;
  else if(output > oldOutputs[i])
   backslashs[i] = hard.OUTPUTS[i].BACKSLASH;

  oldOutputs[i] = output;

  let value = output + backslashs[i];
 }

 applyMotorCommands();
}

function setSleepModes() {
}

setInterval(function() {
 if(!engine)
  return;

 let change = false;
 let predictiveLatency = Date.now() - lastTimestamp;

 if(predictiveLatency < SYS.LATENCYALARMEND && latencyAlarm) {
  trace(predictiveLatency + " ms latency, resuming normal operations", false);
  latencyAlarm = false;
 } else if(predictiveLatency > SYS.LATENCYALARMBEGIN && !latencyAlarm) {
  trace(predictiveLatency + " ms latency, stopping of motors and streams", false);
  latencyAlarm = true;
 }

 if(latencyAlarm) {
  for(let i = 0; i < conf.TX.COMMANDS16.length; i++)
   if(hard.COMMANDS16[i].FAILSAFE)
    floatTargets16[i] = conf.TX.COMMANDS16[i].INIT;

  for(let i = 0; i < conf.TX.COMMANDS8.length; i++)
   if(hard.COMMANDS8[i].FAILSAFE)
    floatTargets8[i] = conf.TX.COMMANDS8[i].INIT;

  for(let i = 0; i < conf.TX.COMMANDS1.length; i++)
   if(hard.COMMANDS1[i].FAILSAFE)
    floatTargets1[i] = conf.TX.COMMANDS1[i].INIT;
 }

 for(let i = 0; i < conf.TX.COMMANDS16.length; i++) {
  if(floatCommands16[i] == floatTargets16[i])
   continue;
  change = true;

  let delta;
  let target = floatTargets16[i];
  let init = conf.TX.COMMANDS16[i].INIT;

  if(Math.abs(target - init) <= margins16[i])
   delta = hard.COMMANDS16[i].RAMPINIT;
  else if((target - init) * (floatCommands16[i] - init) < 0) {
   delta = hard.COMMANDS16[i].RAMPDOWN;
   target = init;
  } else if(Math.abs(target) - Math.abs(floatCommands16[i]) < 0)
   delta = hard.COMMANDS16[i].RAMPDOWN;
  else
   delta = hard.COMMANDS16[i].RAMPUP;

  if(delta <= 0)
   floatCommands16[i] = target;
  else if(floatCommands16[i] - target < -delta)
   floatCommands16[i] += delta;
  else if(floatCommands16[i] - target > delta)
   floatCommands16[i] -= delta;
  else
   floatCommands16[i] = target;
 }

 for(let i = 0; i < conf.TX.COMMANDS8.length; i++) {
  if(floatCommands8[i] == floatTargets8[i])
   continue;
  change = true;

  let delta;
  let target = floatTargets8[i];
  let init = conf.TX.COMMANDS8[i].INIT;

  if(Math.abs(target - init) <= margins8[i])
   delta = hard.COMMANDS8[i].RAMPINIT;
  else if((target - init) * (floatCommands8[i] - init) < 0) {
   delta = hard.COMMANDS8[i].RAMPDOWN;
   target = init;
  } else if(Math.abs(target) - Math.abs(floatCommands8[i]) < 0)
   delta = hard.COMMANDS8[i].RAMPDOWN;
  else
   delta = hard.COMMANDS8[i].RAMPUP;

  if(delta <= 0)
   floatCommands8[i] = target;
  else if(floatCommands8[i] - target < -delta)
   floatCommands8[i] += delta;
  else if(floatCommands8[i] - target > delta)
   floatCommands8[i] -= delta;
  else
   floatCommands8[i] = target;
 }

 for(let i = 0; i < conf.TX.COMMANDS1.length; i++) {
  if(floatCommands1[i] == floatTargets1[i])
   continue;
  change = true;

  let delta;
  if(Math.abs(floatTargets1[i] - conf.TX.COMMANDS1[i].INIT) < 1)
   delta = hard.COMMANDS1[i].RAMPINIT;
  else
   delta = hard.COMMANDS1[i].RAMPUP;

  if(delta <= 0)
   floatCommands1[i] = floatTargets1[i];
  else if(floatTargets1[i] - floatCommands1[i] > delta)
   floatCommands1[i] += delta;
  else if(floatTargets1[i] - floatCommands1[i] < -delta)
   floatCommands1[i] -= delta;
  else
   floatCommands1[i] = floatTargets1[i];
 }

 if(change)
  writeOutputs();
 else if(!up) {
  setSleepModes();
  engine = false }
}, SYS.SERVORATE);

setInterval(function() {
 if(!initDone)
  return;

 let currCpus = OS.cpus();
 let charges = 0;
 let idles = 0;

 for(let i = 0; i < nbCpus; i++) {
  let prevCpu = prevCpus[i];
  let currCpu = currCpus[i];

  charges += currCpu.times.user - prevCpu.times.user;
  charges += currCpu.times.nice - prevCpu.times.nice;
  charges += currCpu.times.sys - prevCpu.times.sys;
  charges += currCpu.times.irq - prevCpu.times.irq;
  idles += currCpu.times.idle - prevCpu.times.idle;
 }
 prevCpus = currCpus;

 cpuLoad = Math.trunc(100 * charges / (charges + idles));
}, SYS.CPURATE);

let prevCpus = OS.cpus();
let nbCpus = prevCpus.length;

setInterval(function() {
 if(!initDone)
  return;

 FS.readFile(SYS.TEMPFILE, function(err, data) {
  socTemp = data / 1000;
 });
}, SYS.TEMPRATE);

setInterval(function() {
 if(!initDone)
  return;

 const STATS = RL.createInterface(FS.createReadStream(SYS.WIFIFILE));

 STATS.on("line", function(ligne) {
  ligne = ligne.split(/\s+/);

  if(ligne[1] == "wlan" + hard.WLANDEVICE + ":") {
   link = ligne[3];
   rssi = ligne[4];
  }
 });
}, SYS.WIFIRATE);

setInterval(function() {
 if(!initDone || !batteryProxy)
  return;

 naoqiCall(batteryProxy, "getBatteryCharge", []).then(function(bat) {
  battery = bat;
 }).catch(function() {});
}, SYS.GAUGERATE);

function setRxCommands() {
 for(let i = 0; i < conf.TX.COMMANDS16.length; i++)
  rx.commandsInt16[i] = tx.computeRawCommand16(i, floatCommands16[i]);
 rx.cameraChoices[0] = tx.cameraChoices[0];
 for(let i = 0; i < conf.TX.COMMANDS8.length; i++)
  rx.commandsInt8[i] = tx.computeRawCommand8(i, floatCommands8[i]);
 for(let i = 0; i < conf.TX.COMMANDS1.length / 8; i++) {
  let commande1 = 0;
  for(let j = 0; j < 8; j++)
   if(floatCommands1[i * 8 + j] > 0)
    commande1 += 1 << j;
  rx.commands1[i] = commande1;
 }
}

function setRxValues() {
 rx.setFloatValue16(0, voltage);
 rx.setFloatValue16(1, battery);
 rx.setFloatValue8(0, cpuLoad);
 rx.setFloatValue8(1, socTemp);
 rx.setFloatValue8(2, link);
 rx.setFloatValue8(3, rssi);
}

setInterval(function() {
 if(up || !initDone)
  return;

 setRxCommands();
 setRxValues();
 USER.SERVERS.forEach(function(server) {
  sockets[server].emit("serveurrobotrx", {
   timestamp: Date.now(),
   data: rx.arrayBuffer
  });
 });
}, SYS.BEACONRATE);

NET.createServer(function(socket) {
 const SEPARATEURNALU = new Buffer.from([0, 0, 0, 1]);
 const SPLITTER = new SPLIT(SEPARATEURNALU);

 trace("H.264 video streaming process is connected to tcp://127.0.0.1:" + SYS.VIDEOLOCALPORT, false);

 SPLITTER.on("data", function(data) {

  if(currentServer) {
   if(latencyAlarm)
    data = new Buffer.from([]);
   sockets[currentServer].emit("serveurrobotvideo", {
    timestamp: Date.now(),
    data: data
   });
  }

 }).on("error", function(err) {
  trace("Error when splitting input stream into H.264 network abstraction layer units", false);
 });

 socket.pipe(SPLITTER);

 socket.on("end", function() {
  trace("H.264 video streaming process is disconnected from tcp://127.0.0.1:" + SYS.VIDEOLOCALPORT, false);
 });

}).listen(SYS.VIDEOLOCALPORT);

process.on("uncaughtException", function(err) {
 let i = 0;
 let errors = err.stack.split("\n");

 while(i < errors.length)
  trace(errors[i++], false);

 trace("Following this uncaught exception, the Node.js process will be terminated automatically", true);
 setTimeout(function() {
  process.exit(1);
 }, 1000);
});

trace("Client ready", true);

connectNaoqi().then(function() {
 trace("NAOqi connected successfully", true);
}).catch(function(err) {
 trace("Failed to connect to NAOqi: " + err.message, true);
});
