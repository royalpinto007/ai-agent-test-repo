function add(a, b) {
  return a + b;
}

function subtract(a, b) {
  return a - b;
}

function multiply(a, b) {
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

function power(base, exp) {
  if (exp === 0) return 1;
  return Math.pow(base, exp);
}

function average(numbers) {
  const sum = numbers.reduce((a, b) => a + b, 0);
  return sum / numbers.length;
}

function factorial(n) {
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
  absoluteDifference
};