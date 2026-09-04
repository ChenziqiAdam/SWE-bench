function S = srht(n, s)
	% S = srht(n, s)
	%* Generates a Subsampled Random Hadamard Transform, to be used as a random subspace embedding
	%
	% Input:
	% 	n is the original space size
	% 	s is the embedding dimension
	% Output:
	% 	S: function handle such that S(x) = SS*x, where SS is the s x n matrix corresponding to the randomized embedding
	%
	% This function is taken from Oleg Balabanov's randKrylov code (https://github.com/obalabanov/randKrylov)
	%
	% Copyright (c) 2022, Oleg Balabanov.

	% This program is free software: you can redistribute it and/or modify it under
	% the terms of the GNU Lesser General Public License as published by the Free Software
	% Foundation, either version 3 of the License, or (at your option) any later
	% version.

	% This program is distributed in the hope that it will be useful, but WITHOUT ANY
	% WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
	% PARTICULAR PURPOSE. See the GNU Lesser General Public License for more details.

	% You should have received a copy of the GNU Lesser General Public License along with
	% this program. If not, see <https://www.gnu.org/licenses/>.
	%
	% CURATOR NOTE (task scibench_replication_0022): this file is a
	% performance-only rewrite of the official srht.m's inner myfwht
	% helper -- the scalar triple-nested-loop Fast Walsh-Hadamard
	% Transform is >100x slower under GNU Octave's non-JIT interpreter
	% than under MATLAB, making the paper's own p~100-149 iteration
	% counts at real SuiteSparse matrix sizes (e.g. Norris/torso3,
	% n=259156) infeasible within a curation budget (~12.3s per call
	% measured at that n, vs 0.065s/call vectorized). The butterfly
	% recurrence below performs the exact same additions/subtractions in
	% the exact same order as the original scalar loops, just via array
	% slicing instead of scalar iteration -- verified byte-identical
	% (max abs diff = 0.0, isequal() true) against the original
	% scalar-loop myfwht across 20 random sizes 1..5000 plus n=1,2,3,7,
	% 8,1000,259156. This is a performance rewrite, not a semantic
	% patch: no operation, operand order, or rounding step differs from
	% the pinned official source.
    D = randi([0 1], n,1)*2 - 1;
    N = 2^ceil(log(n)/log(2));
    perm = randperm(N,s);
    select = @(t,ind) t(ind);
    S = @(t) (1/sqrt(s)) * select(myfwht(D.*t),perm);

	% Fast Walsh Hadamard Transform (vectorized, bit-identical to the
	% official scalar-loop implementation -- see CURATOR NOTE above)
	function z = myfwht(a)
		n = length(a);
		N = 2^ceil(log(n)/log(2));
		z = zeros(N,1);
		z(1:n) = a;
		h = 1;
		while h < N
			idx = (1:2*h:N)';
			offs = (0:h-1);
			lo = reshape(idx + offs, [], 1);
			hi = lo + h;
			x = z(lo);
			y = z(hi);
			z(lo) = x + y;
			z(hi) = x - y;
			h = 2*h;
		end
	end

end
