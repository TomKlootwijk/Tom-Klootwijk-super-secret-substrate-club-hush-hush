#include "sha256.hpp"
#include <algorithm>
#include <cstring>
#include <stdexcept>
namespace ugts41 { namespace {
constexpr std::array<std::uint32_t,64>K={0x428a2f98U,0x71374491U,0xb5c0fbcfU,0xe9b5dba5U,0x3956c25bU,0x59f111f1U,0x923f82a4U,0xab1c5ed5U,0xd807aa98U,0x12835b01U,0x243185beU,0x550c7dc3U,0x72be5d74U,0x80deb1feU,0x9bdc06a7U,0xc19bf174U,0xe49b69c1U,0xefbe4786U,0x0fc19dc6U,0x240ca1ccU,0x2de92c6fU,0x4a7484aaU,0x5cb0a9dcU,0x76f988daU,0x983e5152U,0xa831c66dU,0xb00327c8U,0xbf597fc7U,0xc6e00bf3U,0xd5a79147U,0x06ca6351U,0x14292967U,0x27b70a85U,0x2e1b2138U,0x4d2c6dfcU,0x53380d13U,0x650a7354U,0x766a0abbU,0x81c2c92eU,0x92722c85U,0xa2bfe8a1U,0xa81a664bU,0xc24b8b70U,0xc76c51a3U,0xd192e819U,0xd6990624U,0xf40e3585U,0x106aa070U,0x19a4c116U,0x1e376c08U,0x2748774cU,0x34b0bcb5U,0x391c0cb3U,0x4ed8aa4aU,0x5b9cca4fU,0x682e6ff3U,0x748f82eeU,0x78a5636fU,0x84c87814U,0x8cc70208U,0x90befffaU,0xa4506cebU,0xbef9a3f7U,0xc67178f2U};
constexpr std::uint32_t r(std::uint32_t x,unsigned n){return(x>>n)|(x<<(32U-n));}
}
Sha256::Sha256():state_{0x6a09e667U,0xbb67ae85U,0x3c6ef372U,0xa54ff53aU,0x510e527fU,0x9b05688cU,0x1f83d9abU,0x5be0cd19U}{}
void Sha256::transform(const std::uint8_t p[64]){std::array<std::uint32_t,64>w{};for(std::size_t i=0;i<16;i++){auto j=i*4;w[i]=(std::uint32_t(p[j])<<24U)|(std::uint32_t(p[j+1])<<16U)|(std::uint32_t(p[j+2])<<8U)|p[j+3];}for(std::size_t i=16;i<64;i++){auto a=r(w[i-15],7)^r(w[i-15],18)^(w[i-15]>>3);auto b=r(w[i-2],17)^r(w[i-2],19)^(w[i-2]>>10);w[i]=w[i-16]+a+w[i-7]+b;}auto a=state_[0],b=state_[1],c=state_[2],d=state_[3],e=state_[4],f=state_[5],g=state_[6],h=state_[7];for(std::size_t i=0;i<64;i++){auto S1=r(e,6)^r(e,11)^r(e,25);auto ch=(e&f)^((~e)&g);auto t1=h+S1+ch+K[i]+w[i];auto S0=r(a,2)^r(a,13)^r(a,22);auto maj=(a&b)^(a&c)^(b&c);auto t2=S0+maj;h=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;}state_[0]+=a;state_[1]+=b;state_[2]+=c;state_[3]+=d;state_[4]+=e;state_[5]+=f;state_[6]+=g;state_[7]+=h;}
void Sha256::update(std::span<const std::uint8_t>d){update(d.data(),d.size());}
void Sha256::update(const void*ptr,std::size_t n){if(finished_)throw std::logic_error("sha256 finished");auto*p=static_cast<const std::uint8_t*>(ptr);total_bytes_+=n;while(n){auto take=std::min(n,buffer_.size()-buffer_size_);std::memcpy(buffer_.data()+buffer_size_,p,take);buffer_size_+=take;p+=take;n-=take;if(buffer_size_==64){transform(buffer_.data());buffer_size_=0;}}}
std::array<std::uint8_t,32>Sha256::finish(){if(finished_)throw std::logic_error("sha256 twice");finished_=true;auto bits=total_bytes_*8U;buffer_[buffer_size_++]=0x80;if(buffer_size_>56){while(buffer_size_<64)buffer_[buffer_size_++]=0;transform(buffer_.data());buffer_size_=0;}while(buffer_size_<56)buffer_[buffer_size_++]=0;for(int i=7;i>=0;i--)buffer_[buffer_size_++]=static_cast<std::uint8_t>(bits>>(i*8));transform(buffer_.data());std::array<std::uint8_t,32>o{};for(std::size_t i=0;i<8;i++){o[i*4]=state_[i]>>24;o[i*4+1]=state_[i]>>16;o[i*4+2]=state_[i]>>8;o[i*4+3]=state_[i];}return o;}
std::array<std::uint8_t,32>sha256(std::span<const std::uint8_t>d){Sha256 s;s.update(d);return s.finish();}
std::string hex_bytes(std::span<const std::uint8_t>d){static constexpr char h[]="0123456789abcdef";std::string o(d.size()*2,'0');for(std::size_t i=0;i<d.size();i++){o[i*2]=h[d[i]>>4];o[i*2+1]=h[d[i]&15];}return o;}
std::string hex_digest(std::span<const std::uint8_t>d){auto h=sha256(d);return hex_bytes(h);}
}
