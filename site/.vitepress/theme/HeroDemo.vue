<template>
  <figure class="hero-demo" aria-label="Example: one run_js program navigates a persistent desktop browser and reads the page title">
    <div class="demo-window">
      <div class="demo-bar">
        <span class="demo-dots" aria-hidden="true"><i></i><i></i><i></i></span>
        <span>Agent / run_js</span>
        <span class="demo-label">ONE CALL</span>
      </div>
      <pre class="demo-code"><code><span class="demo-comment">// Open a page. Read its title.</span>
const r = await mcp.callTool(
  "browser", "browser_execute", {
    operations: [
      { type: "navigate", params: {
        url: "https://example.com"
      } },
      { type: "evaluate", params: {
        script: "document.title"
      } },
    ],
  }
)
console.log(r.content[0].text)</code></pre>
    </div>
    <div class="demo-connection" aria-hidden="true"><span>↓</span> your cloud desktop</div>
    <div class="demo-window demo-browser">
      <div class="demo-bar">
        <span class="demo-dots" aria-hidden="true"><i></i><i></i><i></i></span>
        <span class="demo-address">example.com</span>
      </div>
      <div class="demo-page">
        <span class="demo-page-title">Example Domain</span>
        <span class="demo-page-line"></span>
        <span class="demo-page-line short"></span>
        <span class="demo-page-link">Learn more ↗</span>
        <svg class="demo-cursor" width="27" height="32" viewBox="0 0 27 32" aria-hidden="true"><path d="M3 2 L3 25 L9 20 L14 30 L19 27 L14 18 L24 18 Z" fill="var(--paper)" stroke="var(--ink)" stroke-width="2" stroke-linejoin="round" /></svg>
      </div>
      <div class="demo-footer"><span>2 steps · same desktop</span><span class="wf-state">State persists</span></div>
    </div>
    <figcaption>Write code. Use the desktop. Keep your state.</figcaption>
  </figure>
</template>

<style scoped>
.hero-demo { width: 100%; margin: 0; color: var(--ink); text-align: left; }
.demo-window { border: 2px solid var(--ink); border-radius: var(--wobble); overflow: hidden; background: var(--paper); }
.demo-bar { display: flex; align-items: center; gap: 12px; min-height: 42px; padding: 8px 16px; border-bottom: 1px solid var(--pencil); font-size: 12px; font-family: var(--vp-font-family-mono); }
.demo-dots { display: flex; gap: 5px; }
.demo-dots i { width: 7px; height: 7px; border: 1px solid var(--pencil); border-radius: 50%; }
.demo-label { margin-left: auto; font-size: 10px; letter-spacing: 1px; color: var(--pencil); }
.demo-code { margin: 0; padding: 18px 20px; overflow-x: auto; font: 12px/1.65 var(--vp-font-family-mono); }
.demo-comment { color: var(--pencil); }
.demo-connection { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 10px; color: var(--pencil); font: 12px var(--vp-font-family-mono); }
.demo-connection span { font-size: 24px; line-height: 24px; color: var(--ink); }
.demo-address { flex: 1; border: 1px solid var(--pencil); border-radius: 3px; padding: 2px 10px; color: var(--pencil); }
.demo-page { position: relative; padding: 22px 30px; }
.demo-page-title { display: block; font-size: 20px; font-weight: 600; margin-bottom: 12px; }
.demo-page-line { display: block; height: 5px; width: 85%; background: var(--soft); margin: 7px 0; border-radius: 3px; }
.demo-page-line.short { width: 65%; }
.demo-page-link { display: block; margin-top: 12px; font-size: 12px; text-decoration: underline; }
.demo-cursor { position: absolute; right: 60px; bottom: 20px; transform: rotate(-10deg); }
.demo-footer { display: flex; justify-content: space-between; align-items: center; gap: 8px; border-top: 1px dashed var(--pencil); padding: 10px 16px; color: var(--pencil); font-size: 11px; }
.demo-footer .wf-state { font-size: 11px; color: var(--ink); }
figcaption { margin-top: 16px; text-align: center; font-size: 12px; color: var(--pencil); }
@media (max-width: 479px) { .demo-code { font-size: 10px; padding: 14px 12px; } .demo-bar { padding: 8px 12px; gap: 8px; } }
</style>
