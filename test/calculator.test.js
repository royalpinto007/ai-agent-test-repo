const assert = require("assert");
const { add, subtract, multiply, calculateDiscount, getArea, isPrime, celsiusToFahrenheit, clamp, power, average, factorial, percentageOf, isEven, absoluteDifference, roundTo } = require("../src/calculator");

assert.strictEqual(add(2, 3), 5);
assert.strictEqual(subtract(5, 2), 3);
assert.strictEqual(multiply(4, 3), 12);
assert.strictEqual(calculateDiscount(100, true), 80);
assert.strictEqual(calculateDiscount(100, false), 90);
assert.strictEqual(getArea("square", 4), 16);
assert.strictEqual(getArea("circle", 5), Math.PI * 25);
assert.strictEqual(isPrime(2), true);
assert.strictEqual(isPrime(4), false);
assert.strictEqual(isPrime(7), true);
assert.strictEqual(isPrime(9), false);
assert.strictEqual(celsiusToFahrenheit(0), 32);
assert.strictEqual(celsiusToFahrenheit(100), 212);
assert.strictEqual(clamp(5, 1, 10), 5);
assert.strictEqual(clamp(0, 1, 10), 1);
assert.strictEqual(clamp(15, 1, 10), 10);
assert.strictEqual(power(2, 0), 1);
assert.strictEqual(power(2, 3), 8);
assert.strictEqual(power(5, 2), 25);
assert.strictEqual(average([1, 2, 3]), 2);
assert.strictEqual(average([10, 20, 30]), 20);
assert.strictEqual(factorial(0), 1);
assert.strictEqual(factorial(5), 120);
assert.strictEqual(factorial(3), 6);
assert.strictEqual(percentageOf(50, 200), 25);
assert.strictEqual(percentageOf(1, 4), 25);
assert.strictEqual(isEven(4), true);
assert.strictEqual(isEven(3), false);
assert.strictEqual(isEven(0), true);
assert.strictEqual(absoluteDifference(10, 3), 7);
assert.strictEqual(absoluteDifference(3, 10), 7);
assert.strictEqual(absoluteDifference(5, 5), 0);
assert.strictEqual(roundTo(1.456, 2), 1.46);
assert.strictEqual(roundTo(1.454, 2), 1.45);
assert.strictEqual(roundTo(2.5, 0), 3);

// WHY: Issue reported that roundTo() does not support negative decimals for rounding to tens/hundreds.
// These cases verify the negative-decimals branch handles positive values, negative values, zero, and boundary inputs.
assert.strictEqual(roundTo(123.456, -1), 120);
assert.strictEqual(roundTo(123.456, -2), 100);
assert.strictEqual(roundTo(150, -2), 200);
assert.strictEqual(roundTo(99, -2), 100);
assert.strictEqual(roundTo(0, -1), 0);
assert.strictEqual(roundTo(-123.456, -1), -120);
assert.strictEqual(roundTo(-123.456, -2), -100);
// WHY: Number.isFinite() is the correct type check — typeof NaN === 'number' in JS, so typeof alone is insufficient.
assert.strictEqual(Number.isFinite(roundTo(-123.456, -1)), true);

console.log("All tests passed!");