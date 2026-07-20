import type { Metadata } from "next";
import { DemoReplay } from "./demo-replay";

export const metadata: Metadata = {
  title: "Verified API Replay",
  description: "Replay a real Deepgram, Gemini, and GPT-5.6 Luna meeting run without an API key.",
};

export default function DemoPage() {
  return <DemoReplay />;
}
