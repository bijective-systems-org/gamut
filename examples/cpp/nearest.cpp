// The built-in nearest model of examples/07_models.py, fitted in Python and
// evaluated in C++. Run that script first, in this folder: it writes
// lift_nearest.gamut. Both print the same line.
//
// The C++ header covers studies; a model's numbers and the built-in model
// are reached through the C interface, with Study::handle() for the open file.
//
//   c++ -std=c++17 nearest.cpp -I<prefix>/include -L<prefix>/lib -lgamut -o nearest
#include <cstdio>
#include <memory>

#include <gamut/gamut.hpp>

int main() {
  const gamut::Study model = gamut::open("lift_nearest.gamut");
  gamut_error err;
  gamut_tree* tree = nullptr;
  if (gamut_model_numbers(model.handle(), "fit", &tree, &err) != 0) throw gamut::Error(err);
  const std::unique_ptr<gamut_tree, void (*)(gamut_tree*)> numbers(tree, gamut_tree_free);

  const char* inputs[] = {"alpha"};
  const double alpha[] = {2.2, 7.9};
  const double* columns[] = {alpha};
  double lift[2];
  if (gamut_nearest_call(numbers.get(), inputs, columns, 1, 2, "cl", lift, 2, &err) != 0)
    throw gamut::Error(err);
  std::printf("the nearest run's lift at 2.2 and 7.9 degrees: %.2f %.2f\n", lift[0], lift[1]);
}
