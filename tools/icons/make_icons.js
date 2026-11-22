// Draws the Aasra icon and renders every size the web app and the Android app need.
//   cd tools/icons && npm install @resvg/resvg-js@2 && node make_icons.js   (writes to ./out; copy as listed in README)
const { Resvg } = require("@resvg/resvg-js");
const fs = require("fs");
// Aasra icon: a white speech bubble (she talks, it answers) holding a warm gold heart (care), on green.
const BUBBLE = "M168 112 H344 A72 72 0 0 1 416 184 V280 A72 72 0 0 1 344 352 H226 L144 420 L170 352 H168 A72 72 0 0 1 96 280 V184 A72 72 0 0 1 168 112 Z";
const HEART = "M50 88 C20 66 4 48 4 30 C4 16 15 6 28 6 C38 6 46 12 50 20 C54 12 62 6 72 6 C85 6 96 16 96 30 C96 48 80 66 50 88 Z";
const mark = (s = 1, dx = 0, dy = 0) => `
  <g transform="translate(${dx} ${dy}) scale(${s})">
    <path d="${BUBBLE}" fill="#ffffff"/>
    <path d="${HEART}" transform="translate(178.5 160) scale(1.55)" fill="url(#gold)"/>
  </g>`;
const defs = `<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#14904f"/><stop offset="1" stop-color="#075a30"/></linearGradient>
  <linearGradient id="gold" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffc94a"/><stop offset="1" stop-color="#f29a1f"/></linearGradient>
</defs>`;
const svg = {
  // app icon: rounded square
  icon: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">${defs}<rect width="512" height="512" rx="112" fill="url(#bg)"/>${mark(1.1, -25.6, -24)}</svg>`,
  // maskable (web) and adaptive background: full bleed, content inside the 80% safe zone
  maskable: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">${defs}<rect width="512" height="512" fill="url(#bg)"/>${mark(0.78, 56, 62)}</svg>`,
  // Android adaptive foreground (108dp canvas, keep inside the 66dp circle => scale ~0.6)
  foreground: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">${defs}${mark(0.72, 71.7, 64.5)}</svg>`,
  background: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">${defs}<rect width="512" height="512" fill="url(#bg)"/></svg>`,
};
fs.mkdirSync("out", { recursive: true });
fs.writeFileSync("out/icon.svg", svg.icon);
const png = (name, size, file) => fs.writeFileSync(file, new Resvg(svg[name], { fitTo: { mode: "width", value: size } }).render().asPng());
png("icon", 192, "out/icon-192.png"); png("icon", 512, "out/icon-512.png");
png("maskable", 192, "out/icon-192-maskable.png"); png("maskable", 512, "out/icon-512-maskable.png");
png("icon", 180, "out/apple-touch-icon.png"); png("icon", 64, "out/favicon-64.png");
const dens = { mdpi: 1, hdpi: 1.5, xhdpi: 2, xxhdpi: 3, xxxhdpi: 4 };
for (const [d, k] of Object.entries(dens)) {
  fs.mkdirSync(`out/android/mipmap-${d}`, { recursive: true });
  png("icon", Math.round(48 * k), `out/android/mipmap-${d}/ic_launcher.png`);
  png("foreground", Math.round(108 * k), `out/android/mipmap-${d}/ic_launcher_foreground.png`);
  png("background", Math.round(108 * k), `out/android/mipmap-${d}/ic_launcher_background.png`);
}
console.log("ok");
