const assert = require("assert");
const { add, subtract, multiply } = require("../src/calculator");

assert.strictEqual(add(2, 3), 5);
assert.strictEqual(subtract(5, 2), 3);
assert.strictEqual(multiply(4, 3), 12);

console.log("All tests passed!");