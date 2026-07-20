"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { app, BrowserWindow, ipcMain, screen, session } = require("electron");

const projectRoot = path.resolve(process.env.MLT_PROJECT_ROOT || path.join(__dirname, ".."));
const appUrl = new URL(process.env.MLT_APP_URL || "http://127.0.0.1:8765/");
const allowedOrigin = appUrl.origin;
const readyFile = process.env.MLT_DESKTOP_READY_FILE || "";
const preloadPath = path.join(__dirname, "preload.cjs");
const overlayWindows = new Map();
let mainWindow = null;
let mediaWidthPercent = 94;

app.setName("Meeting Live Translator");
app.setPath("userData", path.join(projectRoot, ".run", "electron-user-data"));

const hasLock = app.requestSingleInstanceLock();
if (!hasLock) {
  app.quit();
}

function localUrl(pathname) {
  const target = new URL(pathname, appUrl);
  if (target.origin !== allowedOrigin) throw new Error("Refusing a non-local application URL");
  return target.toString();
}

function hardenWindow(window) {
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event, target) => {
    try {
      if (new URL(target).origin === allowedOrigin) return;
    } catch (_error) {
      // Invalid navigation targets are denied below.
    }
    event.preventDefault();
  });
}

function writeReadyFile() {
  if (!readyFile) return;
  const directory = path.dirname(readyFile);
  fs.mkdirSync(directory, { recursive: true });
  const temporary = `${readyFile}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, String(process.pid), { encoding: "ascii" });
  fs.renameSync(temporary, readyFile);
}

function removeReadyFile() {
  if (!readyFile) return;
  try {
    if (fs.readFileSync(readyFile, "ascii").trim() === String(process.pid)) fs.rmSync(readyFile);
  } catch (_error) {
    // A missing or replaced readiness file belongs to no active cleanup work here.
  }
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1460,
    height: 940,
    minWidth: 960,
    minHeight: 680,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: "#080c14",
    title: "Meeting Live Translator",
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: false,
      additionalArguments: ["--mlt-window-kind=main"],
    },
  });
  hardenWindow(mainWindow);
  mainWindow.once("ready-to-show", () => mainWindow?.show());
  mainWindow.webContents.once("did-finish-load", writeReadyFile);
  mainWindow.on("closed", () => {
    mainWindow = null;
    for (const window of overlayWindows.values()) window.close();
    overlayWindows.clear();
  });
  mainWindow.loadURL(localUrl("/"));
}

function displayForWindow(window = mainWindow) {
  if (window && !window.isDestroyed()) return screen.getDisplayMatching(window.getBounds());
  return screen.getPrimaryDisplay();
}

function overlayBounds(kind, { display = displayForWindow(), widthPercent = mediaWidthPercent } = {}) {
  const workArea = display.workArea;
  if (kind === "media") {
    const maximumWidth = Math.max(320, workArea.width - 24);
    const minimumWidth = Math.min(640, maximumWidth);
    const requestedWidth = Math.round(workArea.width * widthPercent / 100);
    const width = Math.min(maximumWidth, Math.max(minimumWidth, requestedWidth));
    const height = Math.min(220, Math.max(140, workArea.height - 24));
    return {
      width,
      height,
      x: workArea.x + Math.round((workArea.width - width) / 2),
      y: workArea.y + workArea.height - height - 12,
    };
  }
  const size = kind === "caption"
    ? { width: Math.min(1040, workArea.width - 48), height: Math.min(600, workArea.height - 48) }
    : { width: Math.min(570, workArea.width - 48), height: Math.min(780, workArea.height - 48) };
  if (kind === "caption") {
    return {
      ...size,
      x: workArea.x + Math.round((workArea.width - size.width) / 2),
      y: workArea.y + workArea.height - size.height - 24,
    };
  }
  return {
    ...size,
    x: workArea.x + workArea.width - size.width - 24,
    y: workArea.y + Math.round((workArea.height - size.height) / 2),
  };
}

function createOverlay(kind) {
  if (!["caption", "media", "radar"].includes(kind)) return false;
  const existing = overlayWindows.get(kind);
  if (existing && !existing.isDestroyed()) {
    existing.show();
    existing.focus();
    return true;
  }
  const bounds = overlayBounds(kind, { display: displayForWindow(mainWindow) });
  const window = new BrowserWindow({
    ...bounds,
    show: false,
    frame: false,
    transparent: true,
    backgroundColor: "#00000000",
    hasShadow: false,
    resizable: false,
    maximizable: false,
    fullscreenable: false,
    alwaysOnTop: true,
    skipTaskbar: false,
    title: {
      caption: "Meeting Live Translator · Captions",
      media: "Meeting Live Translator · Media Captions",
      radar: "Meeting Live Translator · Decision Radar",
    }[kind],
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: false,
      backgroundThrottling: false,
      additionalArguments: [`--mlt-window-kind=${kind}`],
    },
  });
  overlayWindows.set(kind, window);
  hardenWindow(window);
  window.setAlwaysOnTop(true, "floating");
  window.once("ready-to-show", () => window.show());
  window.on("closed", () => overlayWindows.delete(kind));
  const route = {
    caption: "/captions?native=1",
    media: "/captions?native=1&layout=media",
    radar: "/decision-radar?native=1",
  }[kind];
  window.loadURL(localUrl(route));
  return true;
}

function senderWindow(event) {
  const window = BrowserWindow.fromWebContents(event.sender);
  if (!window || window.isDestroyed()) return null;
  if (window === mainWindow) return window;
  return [...overlayWindows.values()].includes(window) ? window : null;
}

ipcMain.handle("mlt:open-overlay", (event, kind) => {
  if (senderWindow(event) !== mainWindow) return false;
  return createOverlay(String(kind || ""));
});

ipcMain.on("mlt:close-window", (event) => senderWindow(event)?.close());

ipcMain.on("mlt:focus-main-window", () => {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.show();
  mainWindow.focus();
});

ipcMain.handle("mlt:get-window-state", (event) => {
  const window = senderWindow(event);
  return window ? { alwaysOnTop: window.isAlwaysOnTop() } : { alwaysOnTop: false };
});

ipcMain.handle("mlt:set-always-on-top", (event, enabled) => {
  const window = senderWindow(event);
  if (!window || window === mainWindow) return false;
  window.setAlwaysOnTop(Boolean(enabled), "floating");
  return window.isAlwaysOnTop();
});

ipcMain.handle("mlt:set-media-width", (event, widthPercent) => {
  const window = senderWindow(event);
  if (!window || overlayWindows.get("media") !== window) return false;
  const requested = Number(widthPercent);
  if (![60, 80, 94].includes(requested)) return false;
  mediaWidthPercent = requested;
  const display = displayForWindow(window);
  window.setBounds(overlayBounds("media", { display, widthPercent: requested }), false);
  return true;
});

function repositionMediaOverlay() {
  const window = overlayWindows.get("media");
  if (!window || window.isDestroyed()) return;
  window.setBounds(
    overlayBounds("media", { display: displayForWindow(window), widthPercent: mediaWidthPercent }),
    false,
  );
}

app.on("second-instance", () => {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
});

app.whenReady().then(() => {
  session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  screen.on("display-metrics-changed", repositionMediaOverlay);
  screen.on("display-removed", repositionMediaOverlay);
  createMainWindow();
});

app.on("window-all-closed", () => app.quit());
app.on("before-quit", removeReadyFile);
