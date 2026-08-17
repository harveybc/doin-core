# Hybrid-Model Decentralized Evolutionary Computing Using Blockchain and Proof-of-Work Optimization

**Author:** Harvey Demian Bastidas Caicedo  
**Degree:** Master's in Engineering  
**Institution:** Pontificia Universidad Javeriana Cali  
**Year:** 2018

**Original Spanish title:** *Computación Evolutiva Descentralizada de Modelo
Híbrido usando Blockchain y Prueba de Trabajo de Optimización*

[Read the public thesis PDF](<Hybrid-Model Decentralized Evolutionary Computing Using Blockchain and Proof-of-Work Optimization.pdf>).

## Abstract

The thesis proposes an optimization proof of work for a decentralized hybrid
evolutionary-computation system. Instead of spending the computational work
associated with block production on a cryptographic hash puzzle, participating
nodes use that capacity to improve candidate solutions. The blockchain records
optimization operations for traceability and helps synchronize optimization
state across an island-model distributed evolutionary algorithm.

The implementation was evaluated with a reinforcement-learning application for
foreign-exchange trading automation. The experiments examined scalability,
fault tolerance and rejection of invalid optimization results.

## Relationship to DOIN

This thesis is the research origin of DOIN, the Decentralized Optimization and
Inference Network. The current implementation extends the original work and is
organized into three active repositories:

- [doin-core](https://github.com/harveybc/doin-core): protocol models,
  consensus rules, cryptographic identity and plugin interfaces.
- [doin-node](https://github.com/harveybc/doin-node): unified participant
  runtime, networking, blockchain persistence, coordination and analytics.
- [doin-plugins](https://github.com/harveybc/doin-plugins): reference domain
  plugins and adapters for external optimization systems.

## Public Edition

The repository PDF omits the first two administrative front-matter pages from
the university copy because they contained personal contact information. No
research chapter, abstract, result, reference or technical appendix was
removed.
