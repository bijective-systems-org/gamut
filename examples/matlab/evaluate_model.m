%EVALUATE_MODEL The model examples/07_models.py fitted in Python, evaluated
%   in MATLAB with no Python involved. Run that script first, in this
%   folder: it writes lift_model.gamut. Polynomial.m, beside this script,
%   is the MATLAB class of the model's type; both print the same lines.

gamut.registerModelType('Polynomial');
answer = gamut.evaluate('lift_model.gamut', struct('alpha', [2.2; 7.9]));
lift = answer.getScalar('cl');
answer.close();
fprintf('the model''s lift at 2.2 and 7.9 degrees: %s\n', strjoin(compose('%.2f', lift), ' '));

% An angle outside the range the model was fitted on is evaluated, with a
% warning (W4), and the answer says for each row how far outside it lies.
answer = gamut.evaluate('lift_model.gamut', struct('alpha', [5; 12]));
outside = answer.outside('alpha');
answer.close();
fprintf('degrees outside the fitted range: %s\n', strjoin(compose('%g', outside), ' '));
