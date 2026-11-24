// 错误边界：一块内容渲染时抛错，只换掉这一块，页面其余部分照常可用。
// 用在会话写的内容上（答案正文）和任务页的每一栏：内容是别人写的，再怎么防也可能有排不出来的；
// 排不出来就在原地说出来，不让整页被卸掉（那样这道题的任务页以后每次打开都是白屏）。
import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  /** 出错时在原地显示的内容；拿到错误本身，好把原因写出来。 */
  fallback: (error: Error) => ReactNode;
  /** 换了这个值就重新试一次（内容变了、换了一栏）。 */
  resetKey?: unknown;
  children: ReactNode;
};
type State = { error: Error | null; key: unknown };

export class Boundary extends Component<Props, State> {
  state: State = { error: null, key: this.props.resetKey };
  static getDerivedStateFromError(e: unknown): Partial<State> {
    return { error: e instanceof Error ? e : new Error(String(e)) };
  }
  static getDerivedStateFromProps(p: Props, s: State): Partial<State> | null {
    return p.resetKey !== s.key ? { error: null, key: p.resetKey } : null;
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("这一块显示不出来：", error, info.componentStack);
  }
  render() {
    return this.state.error ? this.props.fallback(this.state.error) : this.props.children;
  }
}
