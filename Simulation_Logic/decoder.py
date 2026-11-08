"""
Decoder module for the surface code simulation.
"""
### References: https://nvidia.github.io/cudaq-qec/components/qec/decoders.html
### Reference 2: https://arxiv.org/pdf/2306.09767 (Union-find quantum decoding w/o Union Find, Griffiths et. al (2023))


import qec_aer as qec
from qec_aer import Decoder, DecoderResult, UnionFindDecoder

class decoder(Decoder):
    def __init__(self, num_qubits, syndrome_size):

        self.num_qubits = num_qubits
        self.syndrome_size = syndrome_size
        super().__init__(H=self.num_qubits)
        self.H = self.num_qubits

        self.syndrome = None

    def decode_syndrome(self, syndrome):
        self.syndrome = syndrome
        result = qec.DecoderResult()

        ### Using Union-Find decoder
        result = qec.UnionFindDecoder().decode(self.syndrome)
        result.converged = True

        result.converged = True
        result.result = [0,0] * self.get_block_size()
        return result

    def get_block_size(self):
        return self.num_qubits