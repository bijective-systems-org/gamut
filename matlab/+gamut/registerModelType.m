function registerModelType(className)
%REGISTERMODELTYPE Registers a model type for gamut.evaluate.
%   gamut.registerModelType('mylib.gamut.GP')
%   The class has a constant property Type (its name in model files), a
%   static method load(numbers), and methods call(model, inputs, wanted)
%   and save(model) (SPEC.md section 7.3).  numbers is the model's data as
%   a struct of numbers, text, logicals, arrays and structs.  Registration
%   lasts for the MATLAB session.
%
%   inputs has a field per input the model reads, the row first: a
%   column with a value per row for a parameter or label, rows x nodes x
%   axes for 'coordinates'.  wanted is a cell array of {output, 'values'},
%   {output, 'std'}, {output, 'quantile', q} or {output, 'derivative',
%   name}.  call returns a struct with out.(output).values, .std,
%   .quantiles (a containers.Map from q to values) or .derivatives.(name),
%   as wanted: a value per row for a scalar, rows x nodes for a field.
%   examples/matlab/Polynomial.m is a complete model type.
className = char(className);
mc = meta.class.fromName(className);
if isempty(mc)
    error('gamut:usage', 'no class %s on the MATLAB path', className);
end
type = '';
for k = 1:numel(mc.PropertyList)
    pr = mc.PropertyList(k);
    if strcmp(pr.Name, 'Type') && pr.Constant
        type = pr.DefaultValue;
    end
end
if ~(ischar(type) || isstring(type)) || strlength(type) == 0
    error('gamut:usage', 'a model type has a constant property Type, its name');
end
methods = {mc.MethodList.Name};
for need = {'load', 'call', 'save'}
    if ~any(strcmp(methods, need{1}))
        error('gamut:usage', 'a model type provides %s', need{1});
    end
end
static = mc.MethodList(strcmp(methods, 'load'));
if ~static(1).Static
    error('gamut:usage', 'load is a static method: load(numbers) returns the model');
end
gamut.internal.registry(char(type), className);
end
