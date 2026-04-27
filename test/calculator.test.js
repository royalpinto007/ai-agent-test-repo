const assert = require("assert");
const { add, subtract, multiply, calculateDiscount, getArea, isPrime, celsiusToFahrenheit } = require("../src/calculator");

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

console.log("All tests passed!");
