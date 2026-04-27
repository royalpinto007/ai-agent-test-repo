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

module.exports = {
  add,
  subtract,
  multiply,
  calculateDiscount
};