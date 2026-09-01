import { chmod, mkdir, readFile, rename, stat, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import path from "node:path";
import TOML from "@iarna/toml";
import makeWASocket, { Browsers, DisconnectReason, useMultiFileAuthState } from "@whiskeysockets/baileys";
import pino from "pino";

const configPath = process.env.MAJOR_TOM_CONFIG ?? "/etc/hercules/major-tom/config.toml";
const logger = pino({ level: "silent" });
let reconnecting = false;

function digits(value) {
  return String(value ?? "").replace(/\D/g, "");
}

async function loadConfig() {
  const config = TOML.parse(await readFile(configPath, "utf8"));
  const whatsapp = config.whatsapp ?? {};
  const adminPhone = digits(whatsapp.admin_phone);
  if (!adminPhone) throw new Error("[whatsapp].admin_phone is required in the server config");
  return {
    adminPhone,
    sessionDir: whatsapp.session_dir ?? "/etc/hercules/major-tom/whatsapp-session",
    stateFile: whatsapp.state_file ?? process.env.MAJOR_TOM_WHATSAPP_STATE_FILE ?? "/var/lib/major-tom/whatsapp-state.json",
  };
}

async function writeState(config, patch) {
  const previous = globalThis.bridgeState ?? {};
  globalThis.bridgeState = { ...previous, ...patch, updated_at: new Date().toISOString() };
  await mkdir(path.dirname(config.stateFile), { recursive: true });
  const temporary = `${config.stateFile}.tmp`;
  await writeFile(temporary, JSON.stringify(globalThis.bridgeState));
  await rename(temporary, config.stateFile);
}

function runController(sender, text) {
  const program = process.env.MAJOR_TOM_PYTHON ?? "/usr/bin/python3";
  const args = ["-m", "major_tom.cli", "conversation"];
  return new Promise((resolve) => {
    const child = spawn(program, args, { stdio: ["pipe", "pipe", "ignore"] });
    let output = "";
    child.stdout.on("data", (chunk) => { output += chunk; });
    child.on("error", () => resolve("Major Tom could not start the controller."));
    child.on("close", () => {
      try { resolve(JSON.parse(output).reply ?? "Major Tom received your message."); }
      catch { resolve("Major Tom received your message."); }
    });
    child.stdin.end(JSON.stringify({ sender, text }));
  });
}

async function start() {
  const config = await loadConfig();
  await mkdir(config.sessionDir, { recursive: true, mode: 0o700 });
  await chmod(config.sessionDir, 0o700);
  const { state, saveCreds } = await useMultiFileAuthState(config.sessionDir);
  const sessionReadable = await stat(config.sessionDir).then(() => true, () => false);
  await writeState(config, { connected: false, paired: state.creds.registered, session_readable: sessionReadable, reconnect_healthy: true, reason: state.creds.registered ? "connecting" : "PAIRING_REQUIRED" });
  const sock = makeWASocket({ auth: state, browser: Browsers.ubuntu("Major Tom"), logger, markOnlineOnConnect: false, syncFullHistory: false });
  let pairingRequested = false;
  sock.ev.on("creds.update", saveCreds);
  sock.ev.on("connection.update", async ({ connection, lastDisconnect, qr }) => {
    if (qr && !state.creds.registered && !pairingRequested) {
      pairingRequested = true;
      try {
        const pairingCode = await sock.requestPairingCode(config.adminPhone);
        console.log(`MAJOR TOM WHATSAPP SETUP\nPairing code: ${pairingCode}`);
        await writeState(config, { pairing_code: pairingCode, paired: false, reason: "PAIRING_REQUIRED" });
      } catch (error) {
        pairingRequested = false;
        await writeState(config, { reconnect_healthy: false, reason: `pairing_failed:${error.message}` });
      }
    }
    if (connection === "open") await writeState(config, { connected: true, paired: true, pairing_code: null, reconnect_healthy: true, reason: null });
    if (connection !== "close") return;
    const statusCode = lastDisconnect?.error?.output?.statusCode;
    const loggedOut = statusCode === DisconnectReason.loggedOut;
    await writeState(config, { connected: false, paired: !loggedOut && state.creds.registered, reconnect_healthy: !loggedOut, reason: loggedOut ? "PAIRING_REQUIRED" : "reconnecting" });
    if (!loggedOut && !reconnecting) {
      reconnecting = true;
      setTimeout(() => { reconnecting = false; start().catch((error) => console.error(error)); }, 5000);
    }
  });
  sock.ev.on("messages.upsert", async ({ type, messages }) => {
    if (type !== "notify") return;
    for (const message of messages) {
      if (message.key.fromMe || digits(message.key.remoteJid) !== config.adminPhone) continue;
      const text = message.message?.conversation ?? message.message?.extendedTextMessage?.text;
      if (!text) continue;
      await writeState(config, { last_inbound_at: new Date().toISOString() });
      const reply = await runController(message.key.remoteJid, text);
      await sock.sendMessage(message.key.remoteJid, { text: reply });
      await writeState(config, { last_outbound_at: new Date().toISOString() });
    }
  });
}

start().catch((error) => { console.error(error); process.exitCode = 1; });
