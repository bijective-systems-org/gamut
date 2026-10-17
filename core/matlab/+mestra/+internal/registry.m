function out = registry(type, className)
%REGISTRY Model types registered in this MATLAB session: type -> class name.
persistent map
if isempty(map)
    map = containers.Map('KeyType', 'char', 'ValueType', 'char');
    map('nearest') = 'mestra.Nearest';
end
if nargin == 2
    map(type) = className;
end
if nargin >= 1 && isKey(map, type)
    out = map(type);
else
    out = '';
end
end
