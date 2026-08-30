#pragma once
#include <cstddef>
#include <cstdint>
#include <limits>

namespace kc {

inline constexpr std::size_t MaxGraphRenderRecipes=
    std::numeric_limits<std::uint64_t>::digits;

constexpr std::uint64_t allRenderRecipeCopiesVisible(
    std::size_t recipeCount
) {
    if (recipeCount==0u) return 0u;
    if (recipeCount==MaxGraphRenderRecipes)
        return std::numeric_limits<std::uint64_t>::max();
    if (recipeCount>MaxGraphRenderRecipes) return 0u;
    return (std::uint64_t{1}<<recipeCount)-1u;
}

constexpr bool renderRecipeCopiesVisible(
    std::uint64_t mask,std::size_t recipeCount,std::size_t recipeIndex
) {
    return recipeCount<=MaxGraphRenderRecipes && recipeIndex<recipeCount &&
        (mask&(std::uint64_t{1}<<recipeIndex))!=0u;
}

inline bool setRenderRecipeCopiesVisible(
    std::uint64_t& mask,std::size_t recipeCount,std::size_t recipeIndex,
    bool visible
) {
    if (recipeCount>MaxGraphRenderRecipes || recipeIndex>=recipeCount)
        return false;
    const auto bit=std::uint64_t{1}<<recipeIndex;
    if (visible) mask|=bit;
    else mask&=~bit;
    return true;
}

// Optional bridge from compact Logic Blocks into bounded render-recipe state.
// The target is always one authored scene node. Generated display members do
// not receive graph identities or mutable ECS rows.
class GraphRenderRecipeAccess {
public:
    virtual ~GraphRenderRecipeAccess() = default;
    virtual bool setCopiesVisible(
        std::uint32_t prototypeSceneNode,bool visible
    ) = 0;
};

} // namespace kc
