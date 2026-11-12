// mermaid 初始化 —— mkdocs-material 的 Instant Navigation 会换页面，
// 所以每次换页都要重新初始化一次（document$ 订阅）。
//
// ⚠️ 这个文件住在**源目录** assets/ 下，由 sync_docs.py 同步到
//    docs/assets/。不要直接往 docs/ 里放东西 —— sync_docs.py 每次会
//    清空 docs/ 再重建，放进去的东西会被无声地删掉（这个坑踩过）。
window.mermaidConfig = {
  startOnLoad: false,
  theme: "default",
  securityLevel: "loose",
};

document$.subscribe(() => {
  if (typeof mermaid === "undefined") return;
  // 跟随站点配色：暗色模式用 dark 主题
  const scheme = document.body.getAttribute("data-md-color-scheme") || "default";
  mermaid.initialize({
    startOnLoad: false,
    theme: scheme === "slate" ? "dark" : "default",
    securityLevel: "loose",
  });
  mermaid.run({ querySelector: ".mermaid" }).catch(() => {
    /* 渲染失败就退回成代码块，不影响阅读 */
  });
});
