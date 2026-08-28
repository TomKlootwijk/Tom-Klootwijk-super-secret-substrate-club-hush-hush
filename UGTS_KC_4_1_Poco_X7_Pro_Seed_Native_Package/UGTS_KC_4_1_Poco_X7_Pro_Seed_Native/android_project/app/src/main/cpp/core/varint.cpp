#include "varint.hpp"
namespace ugts41 {
void append_varuint(std::vector<std::uint8_t>& out,std::uint64_t value){while(value>=0x80U){out.push_back(static_cast<std::uint8_t>((value&0x7fU)|0x80U));value>>=7U;}out.push_back(static_cast<std::uint8_t>(value));}
void append_varint(std::vector<std::uint8_t>& out,std::int64_t value){append_varuint(out,(static_cast<std::uint64_t>(value)<<1U)^static_cast<std::uint64_t>(value>>63U));}
bool read_varuint(std::span<const std::uint8_t> data,std::size_t& offset,std::uint64_t& value){value=0;unsigned shift=0;while(offset<data.size()&&shift<=63U){auto b=data[offset++];value|=static_cast<std::uint64_t>(b&0x7fU)<<shift;if(!(b&0x80U))return true;shift+=7U;}return false;}
bool read_varint(std::span<const std::uint8_t> data,std::size_t& offset,std::int64_t& value){std::uint64_t z=0;if(!read_varuint(data,offset,z))return false;value=static_cast<std::int64_t>((z>>1U)^(~(z&1U)+1U));return true;}
}
