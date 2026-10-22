import { authenticatedRequest } from "./client";
import {
  WidgetClient,
  type ChatMessage,
  type ChatSession,
} from "../../../widget/src/client";
export { WidgetClient };
export type { ChatMessage, ChatSession };
export function startPlayground() {
  return authenticatedRequest<ChatSession>("/playground/session", {
    method: "POST",
  });
}
