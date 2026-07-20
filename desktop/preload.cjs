"use strict";

const { contextBridge, ipcRenderer } = require("electron");

const kindArgument = process.argv.find((value) => value.startsWith("--mlt-window-kind="));
const windowKind = kindArgument ? kindArgument.split("=", 2)[1] : "main";

contextBridge.exposeInMainWorld("mltDesktop", Object.freeze({
  isNativeDesktop: true,
  isNativeOverlay: ["caption", "media", "radar"].includes(windowKind),
  windowKind,
  openOverlay: (kind) => ipcRenderer.invoke("mlt:open-overlay", kind),
  closeWindow: () => ipcRenderer.send("mlt:close-window"),
  focusMainWindow: () => ipcRenderer.send("mlt:focus-main-window"),
  getWindowState: () => ipcRenderer.invoke("mlt:get-window-state"),
  setAlwaysOnTop: (enabled) => ipcRenderer.invoke("mlt:set-always-on-top", Boolean(enabled)),
  setMediaWidth: (widthPercent) => ipcRenderer.invoke("mlt:set-media-width", widthPercent),
}));
