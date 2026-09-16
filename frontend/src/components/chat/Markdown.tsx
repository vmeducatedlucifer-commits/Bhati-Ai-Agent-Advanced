import { memo } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { CopyButton } from "@/components/ui/copy-button";
import { cn } from "@/lib/utils";
import { useStore } from "@/lib/store";

function CodeBlock({ className, children }: { className?: string; children?: React.ReactNode }) {
  const language = /language-(\w+)/.exec(className ?? "")?.[1] ?? "";
  const raw = String(children ?? "").replace(/\n$/, "");
  return (
    <div className="group relative my-4 overflow-hidden rounded-xl border border-border bg-[#0d1117] max-w-full">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-1.5">
        <span className="font-mono text-[11px] uppercase tracking-wide text-white/45">
          {language || "code"}
        </span>
        <CopyButton value={raw} className="text-white/50 hover:bg-white/10 hover:text-white" />
      </div>
      <pre className="scrollbar-thin overflow-x-auto p-4 text-[13px] leading-relaxed max-w-full">
        <code className={cn("font-mono block whitespace-pre", className)}>{children}</code>
      </pre>
    </div>
  );
}

export const Markdown = memo(function Markdown({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  const navigateBrowser = useStore((s) => s.navigateBrowser);

  return (
    <div className={cn("prose-chat", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={{
          pre: ({ children }) => <>{children}</>,
          code: ({ className: cls, children, ...props }) => {
            const isBlock = /language-/.test(cls ?? "") || String(children).includes("\n");
            if (!isBlock) {
              return (
                <code className={cn("break-all", cls)} {...props}>
                  {children}
                </code>
              );
            }
            return <CodeBlock className={cls}>{children}</CodeBlock>;
          },
          a: ({ href, children }) => {
            const isLocal = href?.match(/^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0):\d+/i);
            return (
              <a
                href={href}
                target={isLocal ? "_self" : "_blank"}
                rel="noreferrer noopener"
                onClick={(e) => {
                  if (isLocal && href) {
                    e.preventDefault();
                    navigateBrowser(href);
                  }
                }}
              >
                {children}
              </a>
            );
          },
          table: ({ children }) => (
            <div className="scrollbar-thin my-4 overflow-x-auto rounded-lg border border-border max-w-full">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
});
