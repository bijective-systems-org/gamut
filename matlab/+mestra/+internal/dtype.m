function code = dtype(name)
%DTYPE The core's dtype code for a precision name ('' means as given).
switch char(name)
    case '', code = 0;
    case 'float32', code = 5;
    case 'single', code = 5;
    case 'float64', code = 6;
    case 'double', code = 6;
    case 'int64', code = 4;
    otherwise
        error('mestra:E4', 'precision %s is not float32, float64 or int64', name);
end
end
