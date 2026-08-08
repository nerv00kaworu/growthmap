import React from "react";
import { PostPurchasePanel, PostPurchasePanelProps } from "./PostPurchasePanel";
import { projectPublicPostPurchaseSnapshot } from "./model";

/** Server-safe pre-boundary wrapper: validates unknown domain input before creating client props. */
export function PostPurchaseBoundary({ input, ...ports }: { input: unknown } & Omit<PostPurchasePanelProps, "snapshot">) {
  const snapshot = projectPublicPostPurchaseSnapshot(input);
  return <PostPurchasePanel snapshot={snapshot} {...ports} />;
}
