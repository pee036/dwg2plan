// Runs backoffice-web-3d's OWN plan code on a generated Plan JSON.
//   node --experimental-strip-types validate_with_app.mts <plan.json> <path-to-backoffice-web-3d>
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [specPath, appRepo] = process.argv.slice(2);
const lib = await import(pathToFileURL(join(appRepo, "src/lib/planEdit.ts")).href);
const { doorGeometry, polygonArea, baseType, storedSwing, zoneSize } = lib;
const spec = JSON.parse(readFileSync(specPath, "utf8"));
let ok = true;
if (!Array.isArray(spec.zones)) { console.log("FAIL: needs a zones array"); ok = false; }

let sum = 0;
for (const z of spec.zones) {
  const a = polygonArea(z.polygon);
  sum += Math.abs(a);
  const sz = zoneSize(z.polygon);
  console.log(`${String(z.id).padEnd(13)} area=${a.toFixed(2).padStart(6)} bbox=${sz.w}x${sz.d}`);
  if (a <= 0.25) { console.log("  FAIL: non-positive or too small"); ok = false; }
}
console.log("total area", sum.toFixed(1), "declared", spec.area);

const onSeg = (p, a, b, tol = 0.05) => {
  const dx = b[0] - a[0], dz = b[1] - a[1], l2 = dx * dx + dz * dz;
  if (!l2) return false;
  const t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / l2;
  if (t < -0.01 || t > 1.01) return false;
  return Math.hypot(a[0] + t * dx - p[0], a[1] + t * dz - p[1]) < tol;
};
spec.openings.forEach((o, i) => {
  let on = false;
  for (const z of spec.zones) for (let k = 0; k < z.polygon.length; k++) if (onSeg(o.at, z.polygon[k], z.polygon[(k + 1) % z.polygon.length])) on = true;
  let extra = "";
  if (baseType(o.type) === "door") {
    const g = doorGeometry(spec, o);
    extra = ` swing=${g.swing.dir}/${g.swing.hinge} stored=${storedSwing(o.type) ? "yes" : "no"}`;
  }
  console.log(`#${i} ${o.type.padEnd(16)} at=[${o.at}] w=${o.width} onEdge=${on}${extra}`);
  if (!on) ok = false;
});
console.log(ok ? "VALIDATION OK" : "VALIDATION FAILED");
process.exit(ok ? 0 : 1);
