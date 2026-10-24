import { test } from "node:test";
import assert from "node:assert/strict";
import { formatScientific, fullPrecisionTitle } from "../format.ts";

test("rounds a long decimal to 3 significant figures in scientific notation", () => {
  assert.equal(formatScientific(16.361616600246265), "1.64e1");
});

test("formats a small fractional value with a negative exponent", () => {
  assert.equal(formatScientific(0.093), "9.30e-2");
});

test("accepts a numeric string (Decimal-as-string API fields)", () => {
  assert.equal(formatScientific("2.7"), "2.70e0");
});

test("formats zero without a sign or fractional digits", () => {
  assert.equal(formatScientific(0), "0e0");
});

test("formats a negative value with the sign preserved", () => {
  assert.equal(formatScientific(-5.748338739067997), "-5.75e0");
});

test("returns a non-numeric string unchanged instead of corrupting it", () => {
  assert.equal(formatScientific("not a number"), "not a number");
});

test("returns an empty string for null or undefined", () => {
  assert.equal(formatScientific(null), "");
  assert.equal(formatScientific(undefined), "");
});

test("fullPrecisionTitle preserves every digit formatScientific rounds away", () => {
  assert.equal(
    fullPrecisionTitle(16.361616600246265),
    "Full precision: 16.361616600246265",
  );
});

test("fullPrecisionTitle returns a numeric-string field exactly as given, never reformatted", () => {
  assert.equal(fullPrecisionTitle("2.700000"), "Full precision: 2.700000");
});

test("fullPrecisionTitle returns undefined for null or undefined, never a rendered string", () => {
  assert.equal(fullPrecisionTitle(null), undefined);
  assert.equal(fullPrecisionTitle(undefined), undefined);
});
