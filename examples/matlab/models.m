%MODELS Fit, save and evaluate a model of lift versus angle of attack.
%   A model file holds no runs and no code: its parameters carry the range
%   the model was fitted on, each result names the model and output that
%   computes it, and the model's own numbers are plain data. The model here
%   is a quadratic of a type of our own, Polynomial, whose MATLAB class is
%   beside this file. examples/07_models.py is the same program in Python
%   and prints the same lines.

% Training sweep with six converged runs and one failed run.
study = gamut.create('training_sweep.gamut', 'writer', 'example sweep', ...
    'parameters', struct('alpha', struct('units', 'degree', 'role', 'condition')), ...
    'labels', struct('status', struct('role', 'status', 'categories', {{'converged', 'failed'}})), ...
    'scalars', struct('cl', '1'));
for alpha = 0:2:10
    study.addRun(struct('alpha', alpha, 'status', 'converged', 'cl', 0.11 * alpha));
end
study.addRun(struct('alpha', 12, 'status', 'failed'));
study.close();

gamut.registerModelType('Polynomial');

study = gamut.open('training_sweep.gamut');
rows = study.select('status == converged');
alpha = study.getParameter('alpha', 'rows', rows);
cl = study.getScalar('cl', 'rows', rows);
sweepId = study.describe().file_id;
study.close();

model = gamut.createModel('lift_model.gamut', 'writer', 'example fit', 'trainedOn', {sweepId}, ...
    'parameters', struct('alpha', struct('units', 'degree', 'lower', 0, 'upper', 10)), ...
    'scalars', struct('cl', struct('units', '1', 'model', 'fit', 'output', 'cl')));
model.addModel('fit', Polynomial(polyfit(alpha, cl, 2)), {'alpha'});
model.close();

answer = gamut.evaluate('lift_model.gamut', struct('alpha', [2.2; 7.9]), 'path', 'lift_answer.gamut');
lift = answer.getScalar('cl');
answer.close();
fprintf('the model''s lift at 2.2 and 7.9 degrees: %s\n', strjoin(compose('%.2f', lift), ' '));
found = gamut.validate('lift_answer.gamut');
valid = isempty(found) || ~any(startsWith({found.rule}, 'E'));
answers = {'no', 'yes'};
fprintf('the answer is a valid study file: %s\n', answers{valid + 1});

% The built-in model: the closest run, evaluated by the core in every language.
model = gamut.createModel('lift_nearest.gamut', 'writer', 'example fit', 'trainedOn', {sweepId}, ...
    'parameters', struct('alpha', struct('units', 'degree', 'lower', 0, 'upper', 10)), ...
    'scalars', struct('cl', struct('units', '1', 'model', 'fit', 'output', 'cl')));
model.addModel('fit', gamut.Nearest({'alpha'}, 0, 10, alpha, struct('cl', cl)), {'alpha'});
model.close();

answer = gamut.evaluate('lift_nearest.gamut', struct('alpha', [2.2; 7.9]));
lift = answer.getScalar('cl');
answer.close();
fprintf('the nearest run''s lift at 2.2 and 7.9 degrees: %s\n', strjoin(compose('%.2f', lift), ' '));

% Inputs outside the range the model was fitted on are evaluated, with a
% warning (W4), and the answer says for each row how far outside it lies.
answer = gamut.evaluate('lift_model.gamut', struct('alpha', [5; 12]));
lift = answer.getScalar('cl');
outside = answer.outside('alpha');
answer.close();
fprintf('the model''s lift at 5 and 12 degrees: %s\n', strjoin(compose('%.2f', lift), ' '));
fprintf('degrees outside the fitted range: %s\n', strjoin(compose('%g', outside), ' '));

% An input of many values: a wall temperature at four stations is one array.
walls = [300 340 380 420; 500 540 580 620];
model = gamut.createModel('heating_nearest.gamut', 'writer', 'example fit', ...
    'arrays', struct('wall_t', struct('units', 'K', 'length', 4, 'role', 'condition', ...
                                      'lower', 300, 'upper', 620)), ...
    'scalars', struct('q', struct('units', 'kW m-2', 'model', 'fit', 'output', 'q')));
model.addModel('fit', gamut.Nearest({'wall_t'}, 300, 620, walls, struct('q', [41; 35]), 4), {'wall_t'});
model.close();

answer = gamut.evaluate('heating_nearest.gamut', struct('wall_t', [320 350 390 430; 480 530 600 640]));
q = answer.getScalar('q');
outside = answer.outside('wall_t');
answer.close();
fprintf('the nearest run''s heat flux for two walls: %s kW m-2\n', strjoin(compose('%g', q), ' '));
fprintf('kelvin outside the fitted range, second wall: %s\n', strjoin(compose('%g', outside(2, :)), ' '));
