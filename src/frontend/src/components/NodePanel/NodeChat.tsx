"use client";

import { useState, useRef, useEffect } from "react";
import { api } from "@/lib/api";
import { createNodeChatController,mountNodeChatLifecycle } from "@/lib/node-chat-controller";
import { runNodeChatSend } from "@/lib/node-chat-runtime";
import { requestNodeChat } from "@/lib/node-chat-request";
import type { GNode,ProviderConfig } from "@/lib/types";
import { providerActionDisabled } from "@/lib/provider-pending";
import { loadLLMConfig } from "@/lib/llm-provider";
import { useI18n } from "@/i18n/provider";
import { msg } from "@/i18n/ui";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}

interface NodeChatProps {
  selectedNode: GNode;
}

export function NodeChat({ selectedNode }: NodeChatProps) {
  const { locale } = useI18n();
  const m = (tw: string, cn: string, en: string) => msg(locale, {"zh-TW":tw,"zh-CN":cn,en});
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const prevNodeId = useRef<string>(selectedNode.id);
  const controllerRef=useRef<ReturnType<typeof createNodeChatController>|null>(null);
  if(!controllerRef.current)controllerRef.current=createNodeChatController(()=>setLoading(false));
  const controller=controllerRef.current;

  // Reset chat when node changes
  useEffect(() => {
    if (prevNodeId.current !== selectedNode.id) {
      setMessages([]);
      setInput("");
      prevNodeId.current = selectedNode.id;
      controller.invalidate(selectedNode.id);
      setLoading(false);
    }
  }, [selectedNode.id,controller]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);
  useEffect(()=>mountNodeChatLifecycle(controller,window,()=>controller.invalidate(selectedNode.id)),[controller,selectedNode.id]);

  const ancestorPath = selectedNode.ancestor_path || [];
  const breadcrumb = [...ancestorPath.map((a) => a.title), selectedNode.title].join(" › ");
  const [profiles,setProfiles]=useState<ProviderConfig[]>([]);
  useEffect(()=>{api.listProviders().then(setProfiles).catch(()=>setProfiles([]))},[]);
  const selectedConfig=loadLLMConfig();
  const selectedProfile=profiles.find(p=>p.id===selectedConfig?.providerId);
  const chatDisabled=providerActionDisabled(selectedProfile,loading);

  const send = async () => {
    if (!input.trim() || chatDisabled) return;
    const userMsg: ChatMessage = { role: "user", content: input.trim(), timestamp: Date.now() };
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    await runNodeChatSend({capture:(id)=>controller.capture(id),owns:(owner)=>controller.owns(owner),loading:setLoading,request:(owner)=>requestNodeChat(owner,userMsg.content,history,api.chat),publish:(result)=>setMessages((prev)=>[...prev,{role:"assistant",content:result.reply,timestamp:Date.now()}]),error:(e)=>{const code=(e as {code?:string;message?:string}).code||(e as Error).message;const safe=code==="LLM_PROFILE_CHANGED"?m("AI 設定檔已變更，請重新送出。","AI 配置已更改，请重新发送。","The AI profile changed. Send again."):code==="LOCAL_PROFILE_UNAVAILABLE"?m("請先選擇可用的 AI 設定檔。","请先选择可用的 AI 配置。","Select an available AI profile first."):m("AI 暫時無法回應，請重試。","AI 暂时无法响应，请重试。","AI is temporarily unavailable. Please retry.");setMessages(prev=>[...prev,{role:"assistant",content:`❌ ${safe}`,timestamp:Date.now()}])}},selectedNode.id);
  };

  return (
    <div className="flex flex-col gap-2">
      {/* Context indicator */}
      <div className="text-[11px] text-gray-500 bg-gray-900/60 border border-gray-800 rounded-lg px-3 py-2">
        📍 {m("聊天脈絡", "聊天上下文", "Chat context")}：<span className="text-gray-400">{breadcrumb}</span>
      </div>

      {/* Messages */}
      <div className="flex flex-col gap-2 max-h-[360px] overflow-y-auto pr-1">
        {messages.length === 0 && (
          <div className="text-center text-gray-600 text-sm py-6">
            {m("向 AI 顧問提問關於此節點的任何問題", "向 AI 顾问询问有关此节点的任何问题", "Ask the AI advisor anything about this node")}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[85%] rounded-xl px-3 py-2 text-sm whitespace-pre-wrap ${
                m.role === "user"
                  ? "bg-blue-600 text-white rounded-br-sm"
                  : "bg-gray-800 text-gray-200 rounded-bl-sm border border-gray-700"
              }`}
            >
              {m.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-800 border border-gray-700 rounded-xl rounded-bl-sm px-3 py-2 text-sm text-gray-400">
              <span className="animate-pulse">{m("思考中…", "思考中…", "Thinking…")}</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          disabled={chatDisabled}
          placeholder={m("輸入你的問題… (Enter 發送)", "输入你的问题…（按 Enter 发送）", "Enter your question… (Enter to send)")}
          className="flex-1 bg-gray-800/80 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:border-blue-500/70 focus:outline-none disabled:opacity-50"
        />
        <button
          type="button"
          onClick={send}
          disabled={!input.trim() || chatDisabled}
          className="px-3 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm rounded-lg transition-colors shrink-0"
        >
          {m("發送", "发送", "Send")}
        </button>
      </div>
    </div>
  );
}
