const assert = require("assert");
const { add, subtract, multiply, calculateDiscount } = require("../src/calculator");

assert.strictEqual(add(2, 3), 5);
assert.strictEqual(subtract(5, 2), 3);
assert.strictEqual(multiply(4, 3), 12);
assert.strictEqual(calculateDiscount(100, true), 80);
assert.strictEqual(calculateDiscount(100, false), 90);

console.log("All tests passed!");
