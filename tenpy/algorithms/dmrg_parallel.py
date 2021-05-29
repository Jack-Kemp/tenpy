"""Parallelized version of DMRG.

.. warning ::
    This module is still under active development.
"""
# Copyright 2021 TeNPy Developers, GNU GPLv3

from ..tools.thread import Worker

from ..linalg import np_conserved as npc
from .dmrg import TwoSiteDMRGEngine, SingleSiteDMRGEngine
from .mps_common import OneSiteH, TwoSiteH

__all__ = ["DMRGThreadPlusHC", "TwoSiteHThreadPlusHC"]


class TwoSiteHThreadPlusHC(TwoSiteH):
    def __init__(self, *args, plus_hc_worker=None, **kwargs):
        super().__init__(*args, **kwargs)
        assert plus_hc_worker is not None
        self._plus_hc_worker = plus_hc_worker
        if not self.combine:
            raise NotImplementedError("works only with combine=True")
        self.RHeff_for_hc = self.RHeff.transpose(['(p1*.vL)', '(p1.vL*)', 'wL'])

    def matvec(self, theta):
        res = {}
        self._plus_hc_worker.put_task(self.matvec_hc, theta, return_dict=res, return_key="theta")
        theta = super().matvec(theta)
        self._plus_hc_worker.join_tasks()
        theta_hc = res["theta"]
        return theta + theta_hc

    def matvec_hc(self, theta):
        labels = theta.get_leg_labels()
        theta = theta.conj()  # copy!
        theta = npc.tensordot(theta, self.LHeff, axes=['(vL*.p0*)', '(vR*.p0)'])
        theta = npc.tensordot(self.RHeff_for_hc,
                              theta,
                              axes=[['(p1.vL*)', 'wL'], ['(p1*.vR*)', 'wR']])
        theta.iconj().itranspose()
        theta.ireplace_labels(['(vR*.p0)', '(p1.vL*)'], ['(vL.p0)', '(p1.vR)'])
        return theta

    def to_matrix(self):
        mat = super().to_matrix()
        mat_hc = mat.conj().itranspose()
        mat_hc.iset_leg_labels(mat.get_leg_labels())
        return mat + mat_hc

    def adjoint(self):
        return self


class DMRGThreadPlusHC(TwoSiteDMRGEngine):

    EffectiveH = TwoSiteHThreadPlusHC

    def __init__(self, psi, model, options, **kwargs):
        self._plus_hc_worker = Worker("EffectiveHPlusHC worker", max_queue_size=1, daemon=False)
        super().__init__(psi, model, options, **kwargs)

    def make_eff_H(self):
        assert self.env.H.explicit_plus_hc
        assert self._plus_hc_worker is not None
        self.eff_H = self.EffectiveH(self.env,
                                     self.i0,
                                     self.combine,
                                     self.move_right,
                                     plus_hc_worker=self._plus_hc_worker)
        if len(self.ortho_to_envs) > 0:
            self._wrap_ortho_eff_H()

    def run(self):
        with self._plus_hc_worker:
            res = super().run()
        return res
