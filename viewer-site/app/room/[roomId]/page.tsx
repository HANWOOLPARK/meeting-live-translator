import type { Metadata } from "next";
import { ViewerRoom } from "./viewer-room";

export const metadata: Metadata = {
  title: "Live meeting",
  description: "Viewer-only live captions, translation, and evidence-linked Decision Radar",
  robots: { index: false, follow: false, nocache: true },
};

export default async function RoomPage({
  params,
}: {
  params: Promise<{ roomId: string }>;
}) {
  const { roomId } = await params;
  return <ViewerRoom roomId={roomId} />;
}
