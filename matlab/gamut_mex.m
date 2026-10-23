function varargout = gamut_mex(varargin) %#ok<STOUT,INUSD>
%GAMUT_MEX Stands in for the compiled gateway where there is none.
%   The toolbox carries gateways for Linux, Windows and Apple silicon Macs,
%   and build_mex compiles one in a checkout. MATLAB runs a compiled gateway
%   in preference to this file, so this runs only when none was built for
%   this computer.
error('gamut:usage', ['there is no Gamut gateway for this computer (%s); in a checkout, ' ...
    'run build_mex in the matlab folder (docs/install.md)'], computer('arch'));
end
