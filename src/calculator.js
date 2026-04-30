function assertNumeric(label, v) {
  if (typeof v !== 'number' || !Number.isFinite(v)) throw new TypeError(label + ' must be a finite numeric value, got ' + (typeof v === 'number' ? v : typeof v));
}

function add(a, b) {
  assertNumeric('add: a', a);
  assertNumeric('add: b', b);
  return a + b;
}

function subtract(a, b) {
  assertNumeric('subtract: a', a);
  assertNumeric('subtract: b', b);
  return a - b;
}

function multiply(a, b) {
  assertNumeric('multiply: a', a);
  assertNumeric('multiply: b', b);
  return a * b;
}

function calculateDiscount(price, isPremium) {
  return isPremium ? price * 0.8 : price * 0.9;
}

function getArea(shape, value) {
  if (shape === "square") return value * value;
  if (shape === "circle") return Math.PI * value * value;
}

function isPrime(n) {
  if (n < 2) return false;
  if (n === 2) return true;
  if (n % 2 === 0) return false;
  for (let i = 3; i <= Math.sqrt(n); i += 2) {
    if (n % i === 0) return false;
  }
  return true;
}

function celsiusToFahrenheit(c) {
  return (c * 9 / 5) + 32;
}

function clamp(value, min, max) {
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

// typeof alone cannot detect NaN (typeof NaN === 'number'), so Number.isFinite is required
function power(base, exp) {
  assertNumeric('power: base', base);
  assertNumeric('power: exp', exp);
  if (exp === 0) return 1;
  return Math.pow(base, exp);
}

function average(numbers) {
  const sum = numbers.reduce((a, b) => a + b, 0);
  return sum / numbers.length;
}

// factorial(-1) causes infinite recursion; guards are ordered type → integer → sign
function factorial(n) {
  if (typeof n !== 'number' || !Number.isFinite(n)) throw new TypeError('factorial: n must be a finite number, got ' + typeof n);
  if (!Number.isInteger(n)) throw new RangeError('factorial: n must be an integer, got ' + n);
  if (n < 0) throw new RangeError('factorial: n must be non-negative, got ' + n);
  if (n === 0) return 1;
  return n * factorial(n - 1);
}

function percentageOf(value, total) {
  return (value / total) * 100;
}

function isEven(n) {
  return n % 2 === 0;
}

function absoluteDifference(a, b) {
  return Math.abs(a - b);
}

function roundTo(value, decimals) {
  if (decimals < 0) {
    const factor = Math.pow(10, -decimals);
    return Math.round(value / factor) * factor;
  }
  const factor = Math.pow(10, decimals);
  return Math.round(value * factor) / factor;
}

function divide(dividend, divisor) {
  assertNumeric('divide: dividend', dividend);
  assertNumeric('divide: divisor', divisor);
  if (divisor === 0) throw new RangeError('divide: divisor must not be zero');
  return dividend / divisor;
}

function sqrt(n) {
  assertNumeric('sqrt: n', n);
  if (n < 0) throw new RangeError('sqrt: n must not be negative, got ' + n);
  return Math.sqrt(n);
}

module.exports = {
  add,
  subtract,
  multiply,
  calculateDiscount,
  getArea,
  isPrime,
  celsiusToFahrenheit,
  clamp,
  power,
  average,
  factorial,
  percentageOf,
  isEven,
  absoluteDifference,
  roundTo,
  divide,
  sqrt
};