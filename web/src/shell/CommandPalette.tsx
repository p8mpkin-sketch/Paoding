// ⌘K 命令面板：一个输入框搜页面、任务与操作。每条右侧带对应的快捷键，用的时候顺便学会。
import { Command } from "cmdk";
import type { ProblemsView } from "../api/types";
import { navigate, type Route } from "../app/router";
import { THEMES, type Theme } from "../app/theme";
import { Kbd } from "../kit";
import { Plain } from "../ui/registers";

type Props = { open: boolean; onOpenChange: (v: boolean) => void; problems: ProblemsView | null };

const PAGES: { word: string; to: Route; key?: string }[] = [
  { word: "今日", to: { page: "home" } },
  { word: "任务库", to: { page: "problems" } },
  { word: "新建任务", to: { page: "new" }, key: "C" },
  { word: "导入任务集", to: { page: "import" } },
  { word: "读数", to: { page: "readings" } },
];

export function CommandPalette({ open, onOpenChange, problems }: Props) {
  const go = (r: Route) => { onOpenChange(false); navigate(r); };
  const theme = (t: Theme) => { onOpenChange(false); window.dispatchEvent(new CustomEvent("paoding:theme", { detail: t })); };
  return (
    <Command.Dialog open={open} onOpenChange={onOpenChange} label="命令面板" className="k-cmdk k-float" overlayClassName="k-overlay" loop>
      <div className="k-cmdk-in">
        <Command.Input placeholder="搜任务、页面或操作…" data-field="palette" />
        <Kbd>Esc</Kbd>
      </div>
      <Command.List>
        <Command.Empty>没有匹配的结果。</Command.Empty>
        <Command.Group heading="页面">
          {PAGES.map((p) => (
            <Command.Item key={p.word} value={`页面 ${p.word}`} onSelect={() => go(p.to)}>
              <span className="grow">{p.word}</span>{p.key && <Kbd>{p.key}</Kbd>}
            </Command.Item>
          ))}
        </Command.Group>
        {problems && problems.items.length > 0 && (
          <Command.Group heading="任务">
            {problems.items.slice(0, 200).map((p) => (
              <Command.Item key={p.id} value={`任务 ${String(p.title.value)} ${p.id}`} onSelect={() => go({ page: "problem", pid: p.id, asOf: null, node: null })}>
                <span className="grow ell"><Plain text={String(p.title.value) || p.id} /></span><span className="k-mono ink3">{p.id}</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}
        <Command.Group heading="外观">
          {THEMES.map((t) => (
            <Command.Item key={t.id} value={`主题 ${t.word}`} onSelect={() => theme(t.id)}>
              <span className="grow">切换主题：{t.word}</span>
            </Command.Item>
          ))}
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}
