// 网页前端的 ESLint（P2-2）。在 web/ 下跑：npm run lint（即 eslint -c lint/eslint.config.js）。
// 不做类型感知的规则（那要 TypeScript 的语言服务）；类型交给 tsc --noEmit。
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**", "lint/**", "tests/fixtures/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { ecmaVersion: 2023, sourceType: "module", globals: { ...globals.browser, ...globals.node } },
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_", destructuredArrayIgnorePattern: "^_" }],
      "@typescript-eslint/no-explicit-any": "off",
      "no-control-regex": "off",
      eqeqeq: ["error", "always"],
    },
    linterOptions: { reportUnusedDisableDirectives: "error" },
  },
  {
    // src/ 是浏览器代码：不许碰 node 的全局量；也不许引用假后端（HT-12 的另一半在 tests/boundaries）
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser } },
    rules: { "no-restricted-imports": ["error", { patterns: [{ group: ["**/mock/**", "../mock/*"], message: "src/ 不引用 mock/" }] }] },
  },
);
