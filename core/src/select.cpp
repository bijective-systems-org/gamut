#include "select.hpp"

#include <cctype>
#include <cmath>
#include <cstdlib>
#include <map>
#include <memory>

namespace mestra {
namespace internal {

namespace {

//   or     = and { "or" and }
//   and    = not { "and" not }
//   not    = [ "not" ] atom
//   atom   = name op value | "(" or ")"
//   op     = "==" | "!=" | "<" | "<=" | ">" | ">="
//   value  = number | string | word
//   string = '"' { any character but '"' } '"'

struct Token {
  enum Kind { Word, String, Open, Close, End } kind = End;
  std::string text;
  std::size_t at = 0;   // byte offset, for messages
};

std::vector<Token> tokenize(const std::string& s) {
  std::vector<Token> out;
  std::size_t i = 0;
  while (i < s.size()) {
    const char c = s[i];
    if (std::isspace(static_cast<unsigned char>(c))) {
      ++i;
      continue;
    }
    Token t;
    t.at = i;
    if (c == '(' || c == ')') {
      t.kind = c == '(' ? Token::Open : Token::Close;
      t.text = std::string(1, c);
      ++i;
    } else if (c == '"') {
      const std::size_t end = s.find('"', i + 1);
      if (end == std::string::npos) {
        throw Error("", "where: the string starting at character " + std::to_string(i) +
                            " is not closed");
      }
      t.kind = Token::String;
      t.text = s.substr(i + 1, end - i - 1);
      i = end + 1;
    } else {
      std::size_t j = i;
      while (j < s.size() && !std::isspace(static_cast<unsigned char>(s[j])) && s[j] != '(' &&
             s[j] != ')') {
        ++j;
      }
      t.kind = Token::Word;
      t.text = s.substr(i, j - i);
      i = j;
    }
    out.push_back(t);
  }
  Token end;
  end.at = s.size();
  out.push_back(end);
  return out;
}

bool is_op(const std::string& w) {
  return w == "==" || w == "!=" || w == "<" || w == "<=" || w == ">" || w == ">=";
}

bool number(const std::string& w, double* out) {
  if (w.empty()) return false;
  char* end = nullptr;
  const double v = std::strtod(w.c_str(), &end);
  if (end == nullptr || *end != '\0') return false;
  // strtod accepts "nan" and "inf"; the grammar's numbers are decimal.
  for (const char c : w) {
    if (!(std::isdigit(static_cast<unsigned char>(c)) || c == '.' || c == 'e' || c == 'E' ||
          c == '+' || c == '-')) {
      return false;
    }
  }
  *out = v;
  return true;
}

class Parser {
 public:
  Parser(const Reader& r, const std::string& where) : r_(r), toks_(tokenize(where)) {
    rows_ = r.schema().rows;
  }

  std::vector<bool> parse() {
    std::vector<bool> v = parse_or();
    if (peek().kind != Token::End) fail("unexpected \"" + peek().text + "\"");
    return v;
  }

 private:
  const Token& peek() const { return toks_[pos_]; }
  Token next() { return toks_[pos_++]; }
  [[noreturn]] void fail(const std::string& why) const {
    throw Error("", "where: " + why + " at character " + std::to_string(peek().at));
  }

  std::vector<bool> parse_or() {
    std::vector<bool> v = parse_and();
    while (peek().kind == Token::Word && peek().text == "or") {
      next();
      const std::vector<bool> w = parse_and();
      for (std::size_t i = 0; i < v.size(); ++i) v[i] = v[i] || w[i];
    }
    return v;
  }

  std::vector<bool> parse_and() {
    std::vector<bool> v = parse_not();
    while (peek().kind == Token::Word && peek().text == "and") {
      next();
      const std::vector<bool> w = parse_not();
      for (std::size_t i = 0; i < v.size(); ++i) v[i] = v[i] && w[i];
    }
    return v;
  }

  std::vector<bool> parse_not() {
    if (peek().kind == Token::Word && peek().text == "not") {
      next();
      std::vector<bool> v = parse_atom();
      for (std::size_t i = 0; i < v.size(); ++i) v[i] = !v[i];
      return v;
    }
    return parse_atom();
  }

  std::vector<bool> parse_atom() {
    if (peek().kind == Token::Open) {
      next();
      std::vector<bool> v = parse_or();
      if (peek().kind != Token::Close) fail("a \")\" is missing");
      next();
      return v;
    }
    if (peek().kind != Token::Word) fail("a name is expected");
    const Token name = next();
    if (peek().kind != Token::Word || !is_op(peek().text)) {
      fail("an operator (==, !=, <, <=, >, >=) is expected after " + name.text);
    }
    const std::string op = next().text;
    if (peek().kind != Token::Word && peek().kind != Token::String) {
      fail("a value is expected after " + op);
    }
    const Token value = next();
    return compare(name, op, value);
  }

  std::vector<bool> compare(const Token& name, const std::string& op, const Token& value) {
    const Schema& s = r_.schema();
    std::vector<bool> out(static_cast<std::size_t>(rows_), false);
    const Selection all = Selection::all();
    if (const Label* l = s.label(name.text)) {
      if (op != "==" && op != "!=") {
        throw Error("", "where: the label " + name.text + " compares only by == or !=");
      }
      const std::vector<std::string> names = r_.label_names(name.text, all);
      const std::vector<std::string> table = r_.table(l->category);
      bool known = false;
      for (const auto& t : table) known = known || t == value.text;
      if (!known) {
        throw Error("E9", "where: \"" + value.text + "\" is not in the table of " + name.text);
      }
      for (std::size_t i = 0; i < out.size(); ++i) {
        out[i] = (names[i] == value.text) == (op == "==");
      }
      return out;
    }
    const bool scalar = s.result(name.text) != nullptr && s.result(name.text)->where == "scalar";
    if (s.parameter(name.text) == nullptr && !scalar) {
      throw Error("", "where: \"" + name.text + "\" is not a parameter, scalar or label");
    }
    double v = 0.0;
    if (value.kind != Token::Word || !number(value.text, &v)) {
      throw Error("", "where: " + name.text + " compares with a number, and \"" + value.text +
                          "\" is not one");
    }
    std::vector<double> col(static_cast<std::size_t>(rows_));
    if (rows_ > 0) r_.read(name.text, all, all, DType::Float64, col.data(), col.size() * 8);
    for (std::size_t i = 0; i < out.size(); ++i) {
      const double x = col[i];
      if (std::isnan(x)) continue;   // NaN compares false, every way
      if (op == "==") out[i] = x == v;
      else if (op == "!=") out[i] = x != v;
      else if (op == "<") out[i] = x < v;
      else if (op == "<=") out[i] = x <= v;
      else if (op == ">") out[i] = x > v;
      else out[i] = x >= v;
    }
    return out;
  }

  const Reader& r_;
  std::vector<Token> toks_;
  std::size_t pos_ = 0;
  std::int64_t rows_ = 0;
};

}  // namespace

std::vector<std::int64_t> select_rows(const Reader& reader, const std::string& where) {
  Parser p(reader, where);
  const std::vector<bool> keep = p.parse();
  std::vector<std::int64_t> out;
  for (std::size_t i = 0; i < keep.size(); ++i) {
    if (keep[i]) out.push_back(static_cast<std::int64_t>(i));
  }
  return out;
}

}  // namespace internal
}  // namespace mestra
