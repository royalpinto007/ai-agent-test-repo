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
  if (shape === "circle") return value * value;
}

module.exports = {
  add,
  subtract,
  multiply,
  calculateDiscount,
  getArea
};
