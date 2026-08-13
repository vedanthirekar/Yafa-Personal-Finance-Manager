"use client";

import * as React from "react";

import { voiceSocketUrl } from "@/lib/api";
import type { VoiceResult, WsMessage } from "@/lib/types";

export type RecorderState = "idle" | "connecting" | "recording" | "processing" | "error";

/**
 * Microphone capture streamed to the API over a WebSocket.
 *
 * Flow: getUserMedia -> MediaRecorder emits webm/opus chunks -> chunks are
 * sent as binary frames -> the server replies with interim `partial`
 * transcripts and, after `finalize`, one authoritative `final` result.
 *
 * `level` drives the waveform. It is read from an AnalyserNode rather than
 * from the recorded chunks, because the encoded opus data isn't usable for
 * amplitude without decoding it first.
 */
export function useVoiceRecorder() {
  const [state, setState] = React.useState<RecorderState>("idle");
  const [partial, setPartial] = React.useState("");
  const [result, setResult] = React.useState<VoiceResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [level, setLevel] = React.useState(0);
  const [seconds, setSeconds] = React.useState(0);

  const socketRef = React.useRef<WebSocket | null>(null);
  const recorderRef = React.useRef<MediaRecorder | null>(null);
  const streamRef = React.useRef<MediaStream | null>(null);
  const audioCtxRef = React.useRef<AudioContext | null>(null);
  const rafRef = React.useRef<number | null>(null);
  const timerRef = React.useRef<ReturnType<typeof setInterval> | null>(null);

  const cleanup = React.useCallback(() => {
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    if (timerRef.current !== null) clearInterval(timerRef.current);
    rafRef.current = null;
    timerRef.current = null;

    recorderRef.current?.state === "recording" && recorderRef.current.stop();
    recorderRef.current = null;

    // Releasing the tracks is what turns off the browser's recording
    // indicator. Skipping it leaves the mic light on after the user stops.
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;

    void audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;

    setLevel(0);
  }, []);

  // Belt and braces: also clean up if the component unmounts mid-recording.
  React.useEffect(() => () => {
    cleanup();
    socketRef.current?.close();
  }, [cleanup]);

  const start = React.useCallback(async () => {
    setError(null);
    setResult(null);
    setPartial("");
    setSeconds(0);
    setState("connecting");

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
    } catch {
      setError("Microphone access was denied. Allow it in your browser settings.");
      setState("error");
      return;
    }
    streamRef.current = stream;

    // --- level meter -------------------------------------------------------
    const audioCtx = new AudioContext();
    audioCtxRef.current = audioCtx;
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    audioCtx.createMediaStreamSource(stream).connect(analyser);
    const buffer = new Uint8Array(analyser.frequencyBinCount);

    const tick = () => {
      analyser.getByteTimeDomainData(buffer);
      // RMS around the 128 midpoint of unsigned 8-bit PCM.
      let sum = 0;
      for (const sample of buffer) sum += (sample - 128) ** 2;
      setLevel(Math.min(1, Math.sqrt(sum / buffer.length) / 40));
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    // --- socket ------------------------------------------------------------
    const socket = new WebSocket(voiceSocketUrl());
    socket.binaryType = "arraybuffer";
    socketRef.current = socket;

    socket.onmessage = (event) => {
      const message: WsMessage = JSON.parse(event.data);
      if (message.type === "ready") {
        setState("recording");
      } else if (message.type === "partial") {
        setPartial(message.transcript);
      } else if (message.type === "final") {
        setResult(message.result);
        setState("idle");
        socket.close();
      } else if (message.type === "error") {
        setError(message.detail);
        setState("error");
      }
    };

    socket.onerror = () => {
      setError("Lost connection to the server.");
      setState("error");
      cleanup();
    };

    socket.onopen = () => {
      const recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
      recorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0 && socket.readyState === WebSocket.OPEN) {
          void event.data.arrayBuffer().then((buf) => socket.send(buf));
        }
      };

      // 1s timeslices: small enough that previews arrive promptly, large
      // enough that each chunk is a decodable fragment.
      recorder.start(1000);
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    };
  }, [cleanup]);

  const stop = React.useCallback(() => {
    setState("processing");

    const recorder = recorderRef.current;
    const socket = socketRef.current;

    // Flush the tail of the recording before asking the server to finalize,
    // otherwise the last second of speech is dropped.
    if (recorder && recorder.state === "recording") {
      recorder.requestData();
      recorder.stop();
    }

    // A short delay lets the final ondataavailable frame reach the socket
    // ahead of the finalize control frame; the server processes in order.
    setTimeout(() => {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ action: "finalize" }));
      }
      cleanup();
    }, 250);
  }, [cleanup]);

  const cancel = React.useCallback(() => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ action: "cancel" }));
    }
    socketRef.current?.close();
    cleanup();
    setState("idle");
    setPartial("");
  }, [cleanup]);

  const reset = React.useCallback(() => {
    setResult(null);
    setPartial("");
    setError(null);
    setSeconds(0);
    setState("idle");
  }, []);

  return { state, partial, result, error, level, seconds, start, stop, cancel, reset };
}
