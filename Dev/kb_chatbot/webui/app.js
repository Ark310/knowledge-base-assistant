// Contoso KB Assistant - web UI bootstrap.
// Connects to the single Python `bridge` over QWebChannel, then (in later tasks)
// renders the chat, config bar, history, and sources panels. This scaffold just
// proves the channel is live.
"use strict";

window.bridge = null;

function boot() {
  new QWebChannel(qt.webChannelTransport, function (channel) {
    window.bridge = channel.objects.bridge;
    bridge.ping().then(function (r) {
      var el = document.getElementById("boot");
      if (el) el.textContent = "bridge: " + r;
    });
    // Signals wired here in Task 2/3: answerReady, turnFailed, turnProgress.
  });
}

if (typeof QWebChannel !== "undefined") {
  boot();
} else {
  window.addEventListener("DOMContentLoaded", boot);
}
