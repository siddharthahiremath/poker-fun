// Each finished game has one winner. A flat prior makes the chance that A
// really wins more often than B equal to P(Beta(winsA + 1, winsB + 1) > 1/2),
// which is a fair-coin binomial probability. 95% is the line for "significant":
// confident enough to call the gap, in the same direction as a one-sided 5% test.

const EXACT_UNTIL = 4096;
const SIGNIFICANT_AT = 95;

export type Side = "better" | "worse" | "even";

export type Call = {
  index: number;
  name: string;
  label: string;
  pct: number;
  side: Side;
  significant: boolean;
};

function normalCdf(z: number) {
  const t = 1 / (1 + 0.2316419 * Math.abs(z));
  const poly = t * (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  const tail = 0.3989422804014327 * Math.exp(-0.5 * z * z) * poly;
  return z >= 0 ? 1 - tail : tail;
}

// P(Y <= kMax) for Y ~ Binomial(n, 1/2)
function binomialCdfHalf(n: number, kMax: number) {
  if (kMax < 0) return 0;
  if (kMax >= n) return 1;
  const complement = n - kMax - 1;
  const sumTail = complement < kMax;
  const limit = sumTail ? complement : kMax;
  let logP = -n * Math.LN2;
  let sum = 0;
  for (let k = 0; k <= limit; k++) {
    sum += Math.exp(logP);
    logP += Math.log(n - k) - Math.log(k + 1);
  }
  return Math.min(1, Math.max(0, sumTail ? 1 - sum : sum));
}

/** Chance A's true win rate is higher than B's. */
export function chanceBetter(winsA: number, winsB: number) {
  const a = Math.max(0, Math.round(winsA)) + 1;
  const b = Math.max(0, Math.round(winsB)) + 1;
  if (a === b) return 0.5;
  const n = a + b - 1;
  const kMax = a - 1;
  if (n > EXACT_UNTIL) {
    const z = (kMax + 0.5 - n / 2) / (Math.sqrt(n) / 2);
    return normalCdf(z);
  }
  return binomialCdfHalf(n, kMax);
}

export function compare(wins: number, otherWins: number, otherName: string, otherIndex: number): Call {
  const better = chanceBetter(wins, otherWins);
  const pctBetter = Math.round(better * 100);
  if (pctBetter === 50) {
    return { index: otherIndex, name: otherName, label: "50%", pct: 50, side: "even", significant: false };
  }
  const ahead = pctBetter > 50;
  const pct = Math.min(99, ahead ? pctBetter : 100 - pctBetter);
  const side: Side = ahead ? "better" : "worse";
  return {
    index: otherIndex,
    name: otherName,
    label: `${pct}%`,
    pct,
    side,
    significant: pct >= SIGNIFICANT_AT,
  };
}
