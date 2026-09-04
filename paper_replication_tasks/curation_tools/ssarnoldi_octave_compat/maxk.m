function [vals, idx] = maxk(x, k, varargin)
%MAXK Octave compatibility shim for MATLAB's maxk (not implemented in
% Octave 9.4.0). Returns the k largest elements of vector x and their
% original indices, using the same stable descending-sort convention as
% MATLAB's maxk (ties broken by ascending original index). Only the
% (x, k) two-argument vector form used by the official sketch-and-select
% Arnoldi source is implemented; the DIM/'ComparisonMethod' MATLAB options
% are not needed by that source and are intentionally unsupported.
    if ~isvector(x)
        error('maxk shim: only vector input is supported');
    end
    was_row = isrow(x);
    x = x(:);
    [s, i] = sort(x, 'descend');
    k = min(k, numel(x));
    vals = s(1:k);
    idx = i(1:k);
    if was_row
        vals = vals.';
        idx = idx.';
    end
end
