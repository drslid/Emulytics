export type ScreenFrameMeta = {
  capturedAt: string;
  ageAtReceipt: number;
  receivedAt: number;
  frameId: string;
};

export function readScreenFrame(
  headers: Headers,
  receivedAt: number,
): ScreenFrameMeta | null {
  const capturedAt = headers.get("X-Screen-Captured-At");
  const ageText = headers.get("X-Screen-Age");
  const frameId = headers.get("X-Screen-Frame-Id");
  if (
    !capturedAt ||
    !Number.isFinite(Date.parse(capturedAt)) ||
    ageText === null ||
    !ageText.trim() ||
    !frameId ||
    !/^[A-Za-z0-9_-]{8,128}$/.test(frameId)
  )
    return null;
  const ageAtReceipt = Number(ageText);
  if (
    !Number.isFinite(ageAtReceipt) ||
    ageAtReceipt < 0 ||
    !Number.isFinite(receivedAt)
  )
    return null;
  return { capturedAt, ageAtReceipt, receivedAt, frameId };
}

export function screenFrameAge(frame: ScreenFrameMeta, now: number): number {
  return frame.ageAtReceipt + Math.max(0, now - frame.receivedAt) / 1000;
}

export function isScreenFrameFresh(
  frame: ScreenFrameMeta | null,
  now: number,
): boolean {
  return (
    frame !== null && Number.isFinite(now) && screenFrameAge(frame, now) < 3
  );
}
