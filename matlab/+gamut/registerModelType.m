function registerModelType(className)
%REGISTERMODELTYPE Registers a model type for gamut.evaluate.
%   gamut.registerModelType('mylib.gamut.GP')
%   The class has a constant property Type (its name in model files), a
%   static method load(numbers), and methods call(model, inputs, wanted)
%   and save(model) (SPEC.md section 7.3).  numbers is the model's data as
%   a struct.  Registration lasts for the MATLAB session.
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
