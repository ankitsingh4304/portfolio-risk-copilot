// Number formatting in Indian style: ₹12,34,567
const inrFmt = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const numFmt = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

export const inr = (x) => (x == null || Number.isNaN(x) ? "—" : inrFmt.format(x));
export const num = (x) => (x == null || Number.isNaN(x) ? "—" : numFmt.format(x));

/** Fraction to percent text: 0.1234 -> "12.3%" */
export const pct = (x, digits = 1) => (x == null || Number.isNaN(x) ? "—" : `${(x * 100).toFixed(digits)}%`);

/** Already-a-percent to text with a sign: -4.12 -> "−4.1%" */
export const signedPct = (x, digits = 1) => {
  if (x == null || Number.isNaN(x)) return "—";
  const s = Math.abs(x).toFixed(digits);
  return x > 0 ? `+${s}%` : x < 0 ? `−${s}%` : `${s}%`;
};

export const signedInr = (x) => {
  if (x == null || Number.isNaN(x)) return "—";
  return x > 0 ? `+${inr(x)}` : x < 0 ? `−${inr(Math.abs(x))}` : inr(0);
};

export const tone = (x) => (x > 0 ? "gain" : x < 0 ? "loss" : "");

export function shortDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}
