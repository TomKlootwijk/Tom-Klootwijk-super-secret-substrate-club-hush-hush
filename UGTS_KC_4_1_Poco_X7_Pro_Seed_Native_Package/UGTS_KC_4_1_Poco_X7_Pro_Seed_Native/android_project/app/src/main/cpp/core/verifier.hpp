#pragma once
#include "types.hpp"
#include <cstdint>
namespace ugts41 {
enum VerificationReason:std::uint32_t{ReasonNone=0,ReasonOutsideSupport=1U<<0,ReasonIncompatible=1U<<1,ReasonGuardRejected=1U<<2,ReasonLowConfidence=1U<<3,ReasonNumericError=1U<<4,ReasonUncertainty=1U<<5,ReasonMetricUnavailable=1U<<6,ReasonInvalidIdentifier=1U<<7};
struct VerificationPolicy{float confidence_floor=.35f,event_margin=.025f,maximum_uncertainty=5.0f;bool accept_touch=false,accept_tangency=false;};
class ProposalVerifier{public:explicit ProposalVerifier(VerificationPolicy p={}):policy_(p){}VerificationDecision verify(const EventProposal&)const;private:VerificationPolicy policy_;};
}
