// Lint for real bugs only (style is left to the code's own conventions): unused or shadowed things, unsafe
// comparisons, forgotten awaits on promises, duplicate keys. `npm run lint`; CI runs it before every build.
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.ts"],
    languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } },
    rules: {
      "@typescript-eslint/no-explicit-any": "off",          // the WebSocket messages are loosely typed on purpose
      "@typescript-eslint/no-unused-vars": "off",           // tsc noUnusedLocals already checks this
      "@typescript-eslint/no-unused-expressions": "off",    // `a && b()` is used for short UI branches
      "@typescript-eslint/no-non-null-assertion": "off",
      "@typescript-eslint/no-empty-object-type": "off",
      "@typescript-eslint/no-floating-promises": ["error", { ignoreVoid: true, ignoreIIFE: true }],
      "@typescript-eslint/no-misused-promises": ["error", { checksVoidReturn: false }],
      "no-empty": ["error", { allowEmptyCatch: true }],
      "no-constant-condition": ["error", { checkLoops: false }],
      "no-dupe-keys": "error",
      "no-self-compare": "error",
      "no-unmodified-loop-condition": "off",    // the loops stop from closures (`alive`, `stop`) the rule cannot see
      "no-useless-assignment": "off",
      "prefer-const": "off",
      "no-useless-escape": "off",
      "no-control-regex": "off",
      "no-cond-assign": ["error", "except-parens"],
    },
  },
);
