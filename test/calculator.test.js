const assert = require("assert");
const { add, subtract, multiply, calculateDiscount, getArea, isPrime, celsiusToFahrenheit, clamp, power, average, factorial, percentageOf, isEven, absoluteDifference, roundTo, divide, sqrt } = require("../src/calculator");

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
assert.strictEqual(roundTo(123.456, -1), 120);
assert.strictEqual(roundTo(123.456, -2), 100);
assert.strictEqual(roundTo(150, -2), 200);
assert.strictEqual(roundTo(99, -2), 100);
assert.strictEqual(roundTo(0, -1), 0);
assert.strictEqual(roundTo(-123.456, -1), -120);
assert.strictEqual(roundTo(-123.456, -2), -100);
assert.strictEqual(Number.isFinite(roundTo(-123.456, -1)), true);

// power() validation — assert.throws with a class checks instanceof; regex checks message
assert.throws(() => power(null, 2), TypeError);
assert.throws(() => power(null, 2), /base/);
assert.throws(() => power(2, undefined), TypeError);
assert.throws(() => power(2, undefined), /exp/);
assert.throws(() => power('abc', 3), TypeError);
assert.throws(() => power('abc', 3), /base/);
assert.throws(() => power(NaN, 2), TypeError);
assert.throws(() => power(NaN, 2), /base/);
assert.throws(() => power(2, NaN), TypeError);
assert.throws(() => power(2, NaN), /exp/);
assert.throws(() => power(Infinity, 2), TypeError);
assert.throws(() => power(Infinity, 2), /base/);
assert.throws(() => power(true, 2), TypeError);
assert.throws(() => power(true, 2), /numeric/);
assert.throws(() => power([], 2), TypeError);
assert.throws(() => power([], 2), /numeric/);

// factorial() validation
assert.throws(() => factorial(-1), RangeError);
assert.throws(() => factorial(-1), /non-negative/);
assert.throws(() => factorial(-100), RangeError);
assert.throws(() => factorial(-100), /non-negative/);
assert.throws(() => factorial(1.5), RangeError);
assert.throws(() => factorial(1.5), /integer/);
assert.throws(() => factorial(0.9), RangeError);
assert.throws(() => factorial(0.9), /integer/);
assert.throws(() => factorial('abc'), TypeError);
assert.throws(() => factorial(null), TypeError);
assert.throws(() => factorial(Infinity), TypeError);

// divide() happy path
assert.strictEqual(typeof divide, 'function');
assert.strictEqual(divide(10, 2), 5);
assert.strictEqual(divide(7, 2), 3.5);
assert.strictEqual(divide(-10, 2), -5);
assert.strictEqual(divide(10, -2), -5);
assert.strictEqual(divide(0, 5), 0);

// divide() validation
assert.throws(() => divide(10, 0), RangeError);
assert.throws(() => divide(10, 0), /zero/);
assert.throws(() => divide(0, 0), RangeError);
assert.throws(() => divide(-5, 0), RangeError);
assert.throws(() => divide(null, 2), TypeError);
assert.throws(() => divide(null, 2), /dividend/);
assert.throws(() => divide(10, 'x'), TypeError);
assert.throws(() => divide(10, 'x'), /divisor/);
assert.throws(() => divide(undefined, 2), TypeError);
assert.throws(() => divide(undefined, 2), /dividend/);
assert.throws(() => divide(true, 2), TypeError);
assert.throws(() => divide(true, 2), /numeric/);
assert.throws(() => divide([], 2), TypeError);
assert.throws(() => divide([], 2), /numeric/);

// add() validation
assert.throws(() => add('a', 1), TypeError);
assert.throws(() => add('a', 1), /numeric/);
assert.throws(() => add(null, 1), TypeError);
assert.throws(() => add(null, 1), /numeric/);
assert.throws(() => add(true, 5), TypeError);
assert.throws(() => add(true, 5), /numeric/);
assert.throws(() => add([], 1), TypeError);
assert.throws(() => add([], 1), /numeric/);
assert.throws(() => add(1, 'b'), TypeError);
assert.throws(() => add(1, 'b'), /numeric/);

// subtract() validation
assert.throws(() => subtract('a', 1), TypeError);
assert.throws(() => subtract('a', 1), /numeric/);
assert.throws(() => subtract(null, 1), TypeError);
assert.throws(() => subtract(null, 1), /numeric/);
assert.throws(() => subtract(true, 5), TypeError);
assert.throws(() => subtract(true, 5), /numeric/);
assert.throws(() => subtract([], 1), TypeError);
assert.throws(() => subtract([], 1), /numeric/);
assert.throws(() => subtract(1, 'b'), TypeError);
assert.throws(() => subtract(1, 'b'), /numeric/);

// multiply() validation
assert.throws(() => multiply('a', 1), TypeError);
assert.throws(() => multiply('a', 1), /numeric/);
assert.throws(() => multiply(null, 1), TypeError);
assert.throws(() => multiply(null, 1), /numeric/);
assert.throws(() => multiply(true, 5), TypeError);
assert.throws(() => multiply(true, 5), /numeric/);
assert.throws(() => multiply([], 1), TypeError);
assert.throws(() => multiply([], 1), /numeric/);
assert.throws(() => multiply(1, 'b'), TypeError);
assert.throws(() => multiply(1, 'b'), /numeric/);

// sqrt() happy path
assert.strictEqual(sqrt(9), 3);
assert.strictEqual(sqrt(0), 0);
assert.strictEqual(sqrt(4), 2);
assert.strictEqual(sqrt(2), Math.SQRT2);

// sqrt() validation
assert.throws(() => sqrt(-1), RangeError);
assert.throws(() => sqrt(-1), /negative/);
assert.throws(() => sqrt(-100), RangeError);
assert.throws(() => sqrt(-100), /negative/);
assert.throws(() => sqrt('abc'), TypeError);
assert.throws(() => sqrt('abc'), /numeric/);
assert.throws(() => sqrt(null), TypeError);
assert.throws(() => sqrt(null), /numeric/);
assert.throws(() => sqrt(true), TypeError);
assert.throws(() => sqrt(true), /numeric/);
assert.throws(() => sqrt([]), TypeError);
assert.throws(() => sqrt([]), /numeric/);

console.log("All tests passed!");